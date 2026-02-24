"""SceneFileOrganizer - Stash plugin entry point.

Reads stdin JSON from Stash, creates StashInterface with full server_connection
(preserving session cookie for hook re-entry prevention), checks Stash version,
and dispatches to the appropriate mode handler.

The core orchestrator is ``process_scene()`` -- the single shared entry point for
hook mode, bulk mode, and backfill mode. It composes all Phase 5 and Phase 6
modules into the end-to-end rename/move pipeline.
"""

import importlib
import json
import os
import pathlib
import re
import sys
import time
import unicodedata
from dataclasses import dataclass


def _ensure_packages(*packages: str) -> None:
    """Install missing Python packages at runtime via pip."""
    missing = []
    for pkg in packages:
        try:
            importlib.import_module(pkg.split(":")[0] if ":" in pkg else pkg)
        except ImportError:
            missing.append(pkg.split(":")[-1] if ":" in pkg else pkg)

    if not missing:
        return

    is_docker = (
        pathlib.Path("/.dockerenv").is_file()
        or pathlib.Path("/proc/self/cgroup").is_file()
        and "docker" in pathlib.Path("/proc/self/cgroup").read_text()
    )
    cmd = [sys.executable, "-m", "pip", "install",
           "--disable-pip-version-check", "--root-user-action=ignore"]
    if is_docker:
        cmd.append("--break-system-packages")
    cmd.extend(missing)
    os.popen(" ".join(cmd)).read()


_ensure_packages("yaml:pyyaml", "unidecode:Unidecode")

import stashapi.log as log
from stashapi.stashapp import StashInterface

from config_loader import load_config
from exclusions import check_exclusions
from file_operations import (
    cleanup_empty_dirs,
    find_associated_files,
    move_associated_files,
    move_scene_file,
    resolve_unique_filename,
)
from path_builder import build_scene_output
from stash_graphql import (
    fetch_library_paths,
    fetch_scene,
    fetch_scene_ids_paginated,
    is_path_under_library,
    remove_tag_from_scene,
)
from template_engine import select_filename_template, select_path_template

PLUGIN_ID = "scene_file_organizer"

# Module-level plugin directory, set in main() for use by task handlers
# that don't receive json_input (bulk_rename, backfill).
_plugin_dir = ""


@dataclass
class AuditStats:
    """Summary statistics for backfill/audit operations."""
    total: int = 0
    matched: int = 0
    misplaced: int = 0
    would_move: int = 0
    failed: int = 0
    excluded: int = 0


def _normalize_path(path: str) -> str:
    """Normalize a file path for comparison: NFC Unicode + normpath.

    Handles macOS NFD vs Linux NFC differences by normalizing both
    paths to NFC before comparison.
    """
    return unicodedata.normalize("NFC", os.path.normpath(path))


def check_minimum_version(version, minimum: str) -> bool:
    """Check if Stash version meets minimum requirement.

    Args:
        version: StashVersion object with .major, .minor, .patch attributes.
        minimum: Minimum version string (e.g., "0.22.0").

    Returns:
        True if current version >= minimum, or True if parsing fails (graceful fallback).
    """
    try:
        current = (version.major, version.minor, version.patch)
        minimum_parts = tuple(int(x) for x in minimum.split("."))
        return current >= minimum_parts
    except (ValueError, AttributeError):
        log.warning(f"Could not parse Stash version: {version}")
        return True


def is_enabled(stash: StashInterface) -> bool:
    """Check if plugin is enabled via Stash plugin settings.

    Returns False (disabled) by default if no config exists.
    """
    config = stash.find_plugin_config(PLUGIN_ID)
    if config is None:
        return False
    return config.get("enabled", False)


def is_dry_run(stash: StashInterface) -> bool:
    """Check if dry-run mode is active via Stash plugin settings.

    Returns True (dry-run ON) by default if no config exists.
    """
    config = stash.find_plugin_config(PLUGIN_ID)
    if config is None:
        return True
    return config.get("dry_run", True)



def handle_bulk_rename(stash: StashInterface):
    """Task handler: bulk rename all scenes."""
    config = load_config(_plugin_dir)
    if config is None:
        return

    # Get stash version and library paths once
    version = stash.stash_version()
    version_str = str(version)
    library_paths = fetch_library_paths(stash)
    dry_run = is_dry_run(stash)

    # Fetch all scene IDs (lightweight id-only fragment, sorted by id ASC)
    total, scene_ids = fetch_scene_ids_paginated(stash)
    if total == 0:
        log.info("No scenes found to process.")
        return

    log.info(f"Bulk rename: {total} scenes to process (dry_run={dry_run})")

    processed = 0
    moved = 0
    skipped = 0
    failed = 0
    delay = config.general.bulk_delay

    for i, scene_id in enumerate(scene_ids):
        try:
            result = process_scene(
                stash, scene_id, config, library_paths, dry_run, version_str
            )
            if result:
                moved += 1
            else:
                skipped += 1
        except Exception as e:
            log.error(f"Scene {scene_id}: unexpected error: {e}")
            failed += 1

        processed += 1
        log.progress(processed / total)

        if delay > 0 and i < len(scene_ids) - 1:
            time.sleep(delay)

    log.info(
        f"Bulk rename complete: {processed} processed, {moved} moved, "
        f"{skipped} skipped, {failed} failed"
    )
    log.progress(1.0)


def handle_backfill(stash: StashInterface):
    """Task handler: backfill/audit organized scenes.

    Queries only organized scenes, computes expected path for each,
    compares actual vs expected using NFC-normalized comparison.

    In dry-run (audit-only) mode: reports misplaced files without moving.
    In fix mode (dry-run OFF): moves misplaced files via process_scene().
    """
    config = load_config(_plugin_dir)
    if config is None:
        return

    version = stash.stash_version()
    version_str = str(version)
    library_paths = fetch_library_paths(stash)
    dry_run = is_dry_run(stash)

    # Fetch only organized scenes
    total, scene_ids = fetch_scene_ids_paginated(
        stash, scene_filter={"organized": True}
    )
    if total == 0:
        log.info("No organized scenes found.")
        return

    mode_label = "audit-only" if dry_run else "fix"
    log.info(f"Backfill ({mode_label}): {total} organized scenes to check")

    stats = AuditStats(total=total)
    delay = config.general.bulk_delay

    for i, scene_id in enumerate(scene_ids):
        did_work = False
        try:
            # Fetch scene data
            scene = fetch_scene(stash, scene_id, version_str)
            if scene is None:
                stats.failed += 1
                continue

            # Check exclusions
            result = check_exclusions(scene, config.exclusions)
            if result.excluded:
                stats.excluded += 1
                continue

            # Check scene has files
            files = scene.get("files") or []
            if not files:
                stats.failed += 1
                continue

            current_path = files[0]["path"]

            # Compute expected path
            output = build_scene_output(scene, config)
            if output is None:
                stats.failed += 1
                continue

            new_filename, new_dir, _matched_tag = output
            expected_full = os.path.join(new_dir, new_filename)

            # NFC-normalized comparison
            current_normalized = _normalize_path(current_path)
            expected_normalized = _normalize_path(expected_full)

            if current_normalized == expected_normalized:
                stats.matched += 1
                continue

            stats.misplaced += 1
            if dry_run:
                stats.would_move += 1
                log.info(
                    f"[AUDIT] Scene {scene_id}: misplaced\n"
                    f"  Actual:   {current_path}\n"
                    f"  Expected: {expected_full}"
                )
            else:
                # Fix mode: reuse fetched scene data to avoid redundant fetch
                try:
                    success = process_scene(
                        stash, scene_id, config, library_paths,
                        dry_run=False, stash_version_str=version_str,
                        scene_data=scene,
                    )
                    if success:
                        stats.would_move += 1
                        did_work = True
                    else:
                        stats.failed += 1
                except Exception as e:
                    log.error(f"Scene {scene_id}: fix failed: {e}")
                    stats.failed += 1

        except Exception as e:
            log.error(f"Scene {scene_id}: unexpected error: {e}")
            stats.failed += 1
        finally:
            log.progress((i + 1) / total)

            # Only delay after scenes that did actual file I/O
            if did_work and delay > 0 and i < len(scene_ids) - 1:
                time.sleep(delay)

    # Summary report
    log.info(
        f"Backfill complete ({mode_label}):\n"
        f"  Total:      {stats.total}\n"
        f"  Matched:    {stats.matched}\n"
        f"  Misplaced:  {stats.misplaced}\n"
        f"  {'Would-move: ' + str(stats.would_move) if dry_run else 'Moved:      ' + str(stats.would_move)}\n"
        f"  Failed:     {stats.failed}\n"
        f"  Excluded:   {stats.excluded}"
    )
    log.progress(1.0)


def process_scene(
    stash,
    scene_id: int,
    config,
    library_paths: list,
    dry_run: bool = False,
    stash_version_str: str = "",
    scene_data: dict = None,
) -> bool:
    """Orchestrate the full rename/move pipeline for a single scene.

    This is the single shared entry point for hook mode, bulk mode, and
    backfill mode. Composes all Phase 5 and Phase 6 modules:
    fetch -> exclude -> compute -> validate -> move -> associated -> cleanup.

    Args:
        stash: StashInterface instance.
        scene_id: Numeric scene ID to process.
        config: Config dataclass instance.
        library_paths: List of Stash library root paths.
        dry_run: If True, log what would happen without moving files.
        stash_version_str: Stash server version string for fragment selection.
        scene_data: Pre-fetched scene dict to avoid redundant GraphQL fetch.
            If None, the scene is fetched via fetch_scene().

    Returns:
        True if scene was processed (moved or dry-run logged), False if skipped.
    """
    # 1. Fetch scene data (skip if pre-fetched)
    scene = scene_data if scene_data is not None else fetch_scene(stash, scene_id, stash_version_str)
    if scene is None:
        log.warning(f"Scene {scene_id} not found.")
        return False

    # 2. Check exclusions
    result = check_exclusions(scene, config.exclusions)
    if result.excluded:
        log.info(f"Scene {scene_id} excluded by {result.reason}")
        return False

    # 3. Check scene has files
    files = scene.get("files") or []
    if not files:
        log.warning(f"Scene {scene_id} has no files.")
        return False
    file_data = files[0]
    file_id = str(file_data["id"])
    current_path = file_data["path"]

    # 4. Compute rename target
    output = build_scene_output(scene, config)
    if output is None:
        log.warning(f"Scene {scene_id}: build_scene_output returned None.")
        return False
    new_filename, new_path, matched_tag = output
    dest_full = os.path.normpath(os.path.join(new_path, new_filename))
    current_full = os.path.normpath(current_path)

    # 4b. Look up tag modifiers for matched tag
    tag_modifiers = None
    if matched_tag and matched_tag in config.tag_options:
        tag_modifiers = config.tag_options[matched_tag]

    # 4c. Per-tag dry_run override
    effective_dry_run = dry_run
    if tag_modifiers and tag_modifiers.dry_run:
        effective_dry_run = True

    # 5. Same-path short-circuit
    if dest_full == current_full:
        log.debug(f"Scene {scene_id}: already at target path.")
        return False

    # 6. Validate destination under library
    if not is_path_under_library(new_path, library_paths):
        log.error(
            f"Scene {scene_id}: destination '{new_path}' is not under any "
            "library path. Skipping."
        )
        return False

    # 7. Dry-run mode
    if effective_dry_run:
        # Compute template match info for dry-run output
        scene_tags = [t.get("name", "") for t in scene.get("tags", [])]
        scene_studio = (scene.get("studio") or {}).get("name", "")

        fn_template = select_filename_template(
            scene_tags, scene_studio, config.filename
        )
        pt_template = select_path_template(
            scene_tags, scene_studio, current_path, config.path
        )

        # Determine template match description
        fn_match_desc = _describe_template_match(
            fn_template, scene_tags, scene_studio, config.filename, "filename"
        )
        pt_match_desc = _describe_template_match(
            pt_template, scene_tags, scene_studio, config.path, "path"
        )

        # Compute variables used by matched templates
        used_vars = {}
        from metadata_extractor import extract_metadata

        all_vars = extract_metadata(scene, config)
        for tmpl in (fn_template, pt_template):
            if tmpl:
                var_names = re.findall(r"\$(\w+)", tmpl)
                for name in var_names:
                    if name in all_vars:
                        used_vars[name] = all_vars[name]

        # Find associated files
        associated = find_associated_files(
            current_path, config.files.associated_extensions
        )

        # Log dry-run output
        log.info(f"[DRY RUN] Scene {scene_id}:")
        log.info(f"  Old: {current_path}")
        log.info(f"  New: {dest_full}")
        log.info(f"  Filename template: {fn_match_desc}")
        log.info(f"  Path template: {pt_match_desc}")
        log.info(f"  Variables: {used_vars}")
        if associated:
            old_stem = os.path.splitext(os.path.basename(current_path))[0]
            new_stem = os.path.splitext(new_filename)[0]
            for af in associated:
                af_name = os.path.basename(af)
                new_af_name = af_name.replace(old_stem, new_stem, 1)
                log.info(f"  Associated: {af_name} -> {new_af_name}")

        return True

    # 8. Resolve duplicate filename
    unique_name = resolve_unique_filename(
        new_path, new_filename, config.files.max_duplicate_retries
    )
    if unique_name is None:
        log.error(
            f"Scene {scene_id}: exceeded {config.files.max_duplicate_retries} "
            f"duplicate retries for '{new_filename}' in '{new_path}'. Skipping."
        )
        return False
    if unique_name != new_filename:
        log.info(
            f"Scene {scene_id}: duplicate detected, using '{unique_name}'."
        )
        new_filename = unique_name

    # 9. Move video file
    success = move_scene_file(stash, file_id, new_path, new_filename)
    if not success:
        log.error(f"Scene {scene_id}: move failed. File: {current_path}")
        return False
    log.info(f"Moved: {current_path} -> {os.path.join(new_path, new_filename)}")

    # 10. Move associated files
    associated = find_associated_files(
        current_path, config.files.associated_extensions
    )
    if associated:
        old_stem = os.path.splitext(os.path.basename(current_path))[0]
        new_stem = os.path.splitext(new_filename)[0]
        moved = move_associated_files(associated, old_stem, new_stem, new_path)
        for old, new in moved:
            log.info(
                f"  Associated: {os.path.basename(old)} -> "
                f"{os.path.basename(new)}"
            )

    # 11. Cleanup empty directories
    if config.paths.remove_empty_folders:
        source_dir = os.path.dirname(current_path)
        removed = cleanup_empty_dirs(source_dir, library_paths)
        for d in removed:
            log.debug(f"Removed empty directory: {d}")

    # 12. Clean tag removal
    if tag_modifiers and tag_modifiers.clean_tag and not effective_dry_run:
        removed = remove_tag_from_scene(stash, scene_id, matched_tag)
        if removed:
            log.info(f"Scene {scene_id}: removed tag '{matched_tag}' (clean_tag)")
        else:
            log.warning(f"Scene {scene_id}: failed to remove tag '{matched_tag}'")

    return True


def _describe_template_match(template, scene_tags, scene_studio, config, kind):
    """Build a human-readable description of which template matched.

    Args:
        template: The selected template string (or None).
        scene_tags: List of tag names on the scene.
        scene_studio: Studio name string.
        config: FilenameConfig or PathConfig instance.
        kind: "filename" or "path" for the description prefix.

    Returns:
        A string like "tag: !1. JAV" or "studio: Deeper" or "default" or "none".
    """
    if template is None:
        return "none"

    # Check tag_templates
    for tag in scene_tags:
        if tag in config.tag_templates and config.tag_templates[tag] == template:
            return f"tag: {tag}"

    # Check studio_templates
    if scene_studio and scene_studio in config.studio_templates:
        if config.studio_templates[scene_studio] == template:
            return f"studio: {scene_studio}"

    # Check path_templates (only for path config)
    if hasattr(config, "path_templates"):
        for path_pattern, tmpl in config.path_templates.items():
            if tmpl == template:
                return f"path: {path_pattern}"

    # Default
    if config.use_default and template == config.default:
        return "default"

    return "unknown"


def handle_hook(stash: StashInterface, json_input: dict):
    """Handle Scene.Update.Post hook with safety guards.

    Five early-exit guards prevent unnecessary processing:
    1. Plugin must be enabled
    2. hookContext must exist in args
    3. 'organized' must be in inputFields (only process organize events)
    4. organized must be set to True (not False)
    5. scene_id must be present
    """
    # Guard 1: Check if enabled
    if not is_enabled(stash):
        return

    # Guard 2: Extract hook context
    hook_context = json_input.get("args", {}).get("hookContext")
    if not hook_context:
        return

    # Guard 3: Check that 'organized' field was in the update
    input_fields = hook_context.get("inputFields", [])
    if "organized" not in input_fields:
        return

    # Guard 4: Check that organized is being set to True
    hook_input = hook_context.get("input", {})
    if not hook_input.get("organized", False):
        return

    # Guard 5: Extract scene ID
    scene_id = hook_context.get("id")
    if not scene_id:
        return

    # Load config (after all guards pass)
    plugin_dir = json_input.get("server_connection", {}).get("PluginDir", "")
    if not plugin_dir:
        plugin_dir = os.path.dirname(os.path.abspath(__file__))
    config = load_config(plugin_dir)
    if config is None:
        return

    # Get stash version for fragment selection
    version = stash.stash_version()
    version_str = str(version)

    # Fetch library paths once per hook invocation
    library_paths = fetch_library_paths(stash)

    # Check dry-run mode
    dry_run = is_dry_run(stash)

    # Process the scene
    process_scene(
        stash, int(scene_id), config, library_paths, dry_run, version_str
    )


def main():
    """Entry point: read stdin JSON, create StashInterface, dispatch to mode handler."""
    global _plugin_dir

    json_input = json.loads(sys.stdin.read())

    # Store plugin_dir at module level for task handlers that don't receive json_input
    _plugin_dir = json_input.get("server_connection", {}).get("PluginDir", "")
    if not _plugin_dir:
        _plugin_dir = os.path.dirname(os.path.abspath(__file__))

    # Pass COMPLETE server_connection to preserve session cookie
    # (contains VisitedPluginHook tracking for re-entry prevention)
    stash = StashInterface(json_input["server_connection"], force_api_key=True)

    # Generate default config.yaml if it doesn't exist yet
    config_path = os.path.join(_plugin_dir, "config.yaml")
    if not os.path.exists(config_path):
        from config_loader import generate_default_config

        generate_default_config(config_path)
        log.info(
            "Generated default config.yaml at "
            f"{config_path}. Edit it to customize behavior."
        )

    # Version check BEFORE any processing
    version = stash.stash_version()
    if not check_minimum_version(version, "0.22.0"):
        log.error(
            "SceneFileOrganizer requires Stash v0.22.0 or later. "
            f"Current version: {version}. "
            "Please update Stash to use this plugin."
        )
        return

    # Mode dispatch
    mode = json_input.get("args", {}).get("mode", "")

    if mode == "generate_config":
        # Config was already generated above if missing; just confirm.
        if os.path.exists(config_path):
            log.info(f"config.yaml exists at {config_path}")
        return
    elif mode == "bulk":
        handle_bulk_rename(stash)
    elif mode == "backfill":
        handle_backfill(stash)
    else:
        # Hook mode: Scene.Update.Post
        handle_hook(stash, json_input)


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        log.error(f"SceneFileOrganizer error: {e}")
