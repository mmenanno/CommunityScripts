"""Filename and path construction pipeline for SceneFileOrganizer.

Composes template rendering and text processing into sanitized filename
and path strings. Field transforms (field_whitespace_separator,
field_replacer) are applied to variable values before rendering.

The filename builder handles the critical extension-separation pattern:
text processing never touches the file extension (.mp4, .mkv, etc.), and
an empty generated filename falls back to the original filename stem.

The path builder handles $studio_hierarchy expansion into individually-sanitized
nested path segments, ^* current-directory substitution, consecutive folder
deduplication, and performer-in-path overrides.
"""

import os

from metadata_extractor import extract_metadata
from template_engine import render_template, select_filename_template, select_path_template
from text_processor import process_text, sanitize_filename

# Keys that contain real filesystem paths with spaces -- never transform these.
_SKIP_TRANSFORM_KEYS = frozenset({"current_path", "current_filename", "current_directory"})


def _apply_field_transforms(variables: dict, config) -> dict:
    """Apply field_whitespace_separator and field_replacer to variable values.

    Processes variable values in two stages:
      1. field_whitespace_separator: replaces spaces in all variable values
         (except filesystem path keys) with the configured separator.
      2. field_replacer: applies per-variable character replacement using
         config entries like {"$studio": {"replace": "'", "with": ""}}.

    Args:
        variables: Dict of str->str template variables.
        config: TextConfig object with field_whitespace_separator and field_replacer.

    Returns:
        New dict with transformed values (does NOT mutate input).
    """
    result = dict(variables)

    # Stage 1: field_whitespace_separator
    if config.field_whitespace_separator:
        separator = config.field_whitespace_separator
        for key in result:
            if key not in _SKIP_TRANSFORM_KEYS:
                result[key] = result[key].replace(" ", separator)

    # Stage 2: field_replacer
    if config.field_replacer:
        for field_name, replacement in config.field_replacer.items():
            # Strip "$" prefix from field_name to get the variable name
            var_name = field_name.lstrip("$")
            if var_name in result and result[var_name]:
                char_to_replace = replacement.get("replace", "")
                char_replacement = replacement.get("with", "")
                result[var_name] = result[var_name].replace(
                    char_to_replace, char_replacement
                )

    return result


def build_filename(filename_template: str, variables: dict, config, original_filename: str) -> str:
    """Build a sanitized filename from template, variables, and config.

    Separates the extension from the original filename, renders the template,
    processes text through the full pipeline, applies fallback for empty results,
    and reattaches the extension verbatim.

    The extension is separated BEFORE text processing to prevent sanitization
    from corrupting file extensions (e.g., removing dots, titlecasing ".mp4").

    Args:
        filename_template: Template string (e.g., "$date $title").
        variables: Dict of template variables (already field-transformed).
        config: Config object (needs config.text for process_text).
        original_filename: The original filename with extension (e.g., "scene.mp4").

    Returns:
        Sanitized filename with extension (e.g., "2024-01-15 Scene Title.mp4").
    """
    # Separate extension from original filename
    stem, ext = os.path.splitext(original_filename)

    # Render template with variable substitution
    rendered = render_template(filename_template, variables)

    # Process text through the full pipeline (sanitization, titlecase, etc.)
    processed = process_text(rendered, config.text)

    # Fallback: if processed result is empty or whitespace-only, use original stem
    if not processed.strip():
        processed = stem

    return processed + ext


def _expand_studio_hierarchy(hierarchy_str: str, separator: str) -> str:
    """Expand studio hierarchy into sanitized nested path segments.

    The metadata extractor stores hierarchy as a "/"-joined string
    (e.g., "MindGeek/Brazzers/Deeper"). This function splits on "/",
    sanitizes each segment individually (removing OS-illegal characters),
    and rejoins with os.sep.

    Args:
        hierarchy_str: "/"-joined hierarchy string from metadata extractor.
        separator: The space_char separator for sanitize_filename.

    Returns:
        os.sep-joined sanitized path segments, or "" if input is empty.
    """
    if not hierarchy_str:
        return ""
    segments = hierarchy_str.split("/")
    sanitized = [sanitize_filename(seg, separator) for seg in segments if seg]
    return os.sep.join(sanitized)


def _substitute_current_dir(path_template: str, current_file_path: str) -> str:
    """Replace ^* with the scene's current parent directory.

    Must be called BEFORE template rendering to prevent the * character
    from being sanitized away by text processing.

    Args:
        path_template: Path template string (may contain ^*).
        current_file_path: Full path to the scene's current file.

    Returns:
        Template with ^* replaced by current directory, or unchanged if no ^*.
    """
    if "^*" not in path_template:
        return path_template
    current_dir = os.path.dirname(current_file_path)
    return path_template.replace("^*", current_dir)


def _deduplicate_consecutive(segments: list) -> list:
    """Remove consecutive identical folder segments.

    Example: ["media", "Deeper", "Deeper", "videos"]
          -> ["media", "Deeper", "videos"]

    This handles cases where the studio name appears in both
    the path template and the studio hierarchy.

    Args:
        segments: List of path segment strings.

    Returns:
        List with consecutive duplicates removed.
    """
    if not segments:
        return segments
    result = [segments[0]]
    for i in range(1, len(segments)):
        if segments[i] != segments[i - 1]:
            result.append(segments[i])
    return result


def _apply_performer_path_overrides(variables: dict, config, current_file_path: str) -> dict:
    """Apply performer-in-path overrides for path rendering.

    Handles three config options that modify the performer variable
    for path rendering only (does NOT affect filename rendering):
      - keep_existing_performer_folder: preserve existing performer folder
      - single_performer_in_path: use only the first performer
      - no_performer_folder: substitute "NoPerformer" when empty

    Ordering: keep_existing_performer_folder runs before single_performer_in_path,
    because keep_existing selects a specific performer from the full list, while
    single_performer takes only the first. If keep_existing already found a match,
    single_performer should NOT override it (the result is already a single performer).

    Args:
        variables: Dict of template variables.
        config: Config object (needs config.paths for path management settings).
        current_file_path: Full path to the scene's current file.

    Returns:
        New dict with performer variable possibly overridden (does NOT mutate input).
    """
    result = dict(variables)
    performer = result.get("performer", "")

    # 1. keep_existing_performer_folder: check if any performer name
    #    appears in the current path segments
    if config.paths.keep_existing_performer_folder and performer:
        path_parts = current_file_path.replace("\\", "/").split("/")
        performer_names = [p.strip() for p in performer.split(", ")]
        found_existing = False
        for name in performer_names:
            if name in path_parts:
                result["performer"] = name
                found_existing = True
                break
        # If keep_existing found a match, skip single_performer_in_path
        if found_existing:
            return result

    # 2. single_performer_in_path: take only the first performer
    if config.paths.single_performer_in_path and performer:
        first = performer.split(", ")[0]
        result["performer"] = first

    # 3. no_performer_folder: substitute "NoPerformer" when empty
    if config.paths.no_performer_folder and not result.get("performer"):
        result["performer"] = "NoPerformer"

    return result


def build_path(path_template: str, variables: dict, config, current_file_path: str) -> str:
    """Build a sanitized directory path from template + variables.

    Pipeline:
      1. Substitute ^* with current parent directory
      2. Apply performer path overrides
      3. Split template on "/" (template convention)
      4. Process each segment (expand $studio_hierarchy specially)
      5. Preserve leading separator for absolute paths
      6. Deduplicate consecutive folders (if enabled)
      7. Join with os.sep

    Args:
        path_template: Path template using "/" as separator (e.g., "$studio/$title").
        variables: Dict of template variables (already field-transformed).
        config: Config object (needs config.text and config.paths).
        current_file_path: The scene's current file path.

    Returns:
        Sanitized directory path string using os.sep.
    """
    # Step 1: ^* substitution (before template rendering)
    template = _substitute_current_dir(path_template, current_file_path)

    # Step 2: Apply performer path overrides
    path_vars = _apply_performer_path_overrides(variables, config, current_file_path)

    # Step 3: Split template on "/" (the template convention)
    raw_segments = template.split("/")

    # Step 4: Process each segment
    processed_segments = []
    for segment in raw_segments:
        if "$studio_hierarchy" in segment:
            # Handle $studio_hierarchy expansion
            hierarchy_str = path_vars.get("studio_hierarchy", "")
            if hierarchy_str:
                # Remove $studio_hierarchy from segment; process remaining content
                remaining = segment.replace("$studio_hierarchy", "")
                if remaining.strip():
                    rendered = render_template(remaining, path_vars)
                    processed = process_text(rendered, config.text)
                    if processed:
                        processed_segments.append(processed)
                # Expand hierarchy into individual sanitized segments
                expanded = _expand_studio_hierarchy(hierarchy_str, config.text.space_char)
                for part in expanded.split(os.sep):
                    if part:
                        processed_segments.append(part)
            # else: hierarchy is empty, skip the segment entirely
        else:
            rendered = render_template(segment, path_vars)
            processed = process_text(rendered, config.text)
            if processed:
                processed_segments.append(processed)

    # Step 5: Handle leading separator for absolute paths (Unix /media/...)
    if raw_segments and raw_segments[0] == "":
        processed_segments.insert(0, "")

    # Step 6: Deduplicate consecutive identical segments
    if config.paths.prevent_consecutive_folders:
        processed_segments = _deduplicate_consecutive(processed_segments)

    return os.sep.join(processed_segments)


def _reduce_path_length(
    variables: dict,
    config,
    filename_template: str,
    path_template: str,
    original_filename: str,
    current_file_path: str,
) -> tuple:
    """Iteratively remove variable values to fit combined path under max_length.

    Copies the variables dict, then loops through config.paths.length_reduction_order.
    For each field that has a truthy value, sets it to "" and regenerates both
    filename and path. Stops as soon as the combined path fits under max_length,
    or returns best-effort result if all fields are exhausted.

    Args:
        variables: Dict of template variables (already field-transformed).
        config: Config object (needs config.paths.max_length, length_reduction_order, config.text).
        filename_template: Template for filename generation.
        path_template: Template for path generation.
        original_filename: Original filename with extension.
        current_file_path: Current file path for path builder.

    Returns:
        (filename, path) tuple with reduced path length.
    """
    # Build initial filename and path with all variables
    filename = build_filename(filename_template, variables, config, original_filename)
    path = build_path(path_template, variables, config, current_file_path)

    full_path = os.path.join(path, filename)
    if len(full_path) <= config.paths.max_length:
        return (filename, path)

    # Iteratively reduce fields
    reduced_vars = dict(variables)
    for field in config.paths.length_reduction_order:
        var_name = field.lstrip("$")
        if not reduced_vars.get(var_name):
            continue  # Skip already-empty fields
        reduced_vars[var_name] = ""
        filename = build_filename(filename_template, reduced_vars, config, original_filename)
        path = build_path(path_template, reduced_vars, config, current_file_path)
        full_path = os.path.join(path, filename)
        if len(full_path) <= config.paths.max_length:
            return (filename, path)

    # Best effort: return whatever we have after all reductions exhausted
    return (filename, path)


def build_scene_output(scene: dict, config) -> tuple | None:
    """Top-level pipeline orchestrator: scene data dict + Config -> (filename, path, matched_tag).

    Composes the full pipeline:
      1. Check for files (return None if no files)
      2. Extract metadata variables
      3. Apply field transforms
      4. Select filename and path templates
      5. Determine matched tag for modifier lookup
      6. Apply tag modifiers (e.g., inverse_performer)
      7. Build filename and path from templates
      8. Apply length reduction if path exceeds max_length

    This is the public API of the path_builder module. Phase 6 calls this
    function to compute rename targets for each scene.

    Args:
        scene: Stash scene GraphQL data dict.
        config: Config object with all configuration sections.

    Returns:
        (new_filename, new_path, matched_tag) tuple, or None if scene has no files.
        matched_tag is the first scene tag found in filename or path tag_templates,
        or None if no tag template matched.
    """
    # Step 1: Get files list
    files = scene.get("files") or []
    if not files:
        return None

    current_file_path = files[0].get("path", "")
    original_filename = os.path.basename(current_file_path)

    # Step 2: Extract metadata
    variables = extract_metadata(scene, config)

    # Step 3: Apply field transforms
    variables = _apply_field_transforms(variables, config.text)

    # Step 4: Get scene metadata for template selection
    scene_tags = [t.get("name", "") for t in scene.get("tags", [])]
    scene_studio = variables.get("studio", "")

    # Step 5: Select templates
    filename_template = select_filename_template(scene_tags, scene_studio, config.filename)
    path_template = select_path_template(
        scene_tags, scene_studio, current_file_path, config.path
    )

    # Step 5b: Determine matched tag for modifier lookup
    matched_tag = None
    for tag in scene_tags:
        if tag in config.filename.tag_templates or tag in config.path.tag_templates:
            matched_tag = tag
            break

    # Step 5c: Apply tag modifiers to variables
    tag_modifiers = config.tag_options.get(matched_tag) if matched_tag else None
    if tag_modifiers and tag_modifiers.inverse_performer and variables.get("performer"):
        from metadata_extractor import _invert_performer_names

        variables["performer"] = _invert_performer_names(
            variables["performer"], config.performers.separator
        )

    # Step 6: Build filename
    if filename_template:
        new_filename = build_filename(filename_template, variables, config, original_filename)
    else:
        new_filename = original_filename

    # Step 7: Build path
    if path_template:
        new_path = build_path(path_template, variables, config, current_file_path)
    else:
        new_path = os.path.dirname(current_file_path)

    # Step 8: Length reduction
    if filename_template or path_template:
        full_path = os.path.join(new_path, new_filename)
        if len(full_path) > config.paths.max_length:
            # For reduction, use actual templates; if one was None, use a
            # passthrough that reproduces the original value.
            fn_tmpl = filename_template if filename_template else "$current_filename"
            pt_tmpl = path_template if path_template else "^*"
            # Add filesystem context variables for passthrough templates
            reduction_vars = dict(variables)
            reduction_vars["current_filename"] = os.path.splitext(original_filename)[0]
            reduction_vars["current_directory"] = os.path.dirname(current_file_path)
            new_filename, new_path = _reduce_path_length(
                reduction_vars, config, fn_tmpl, pt_tmpl,
                original_filename, current_file_path
            )

    return (new_filename, new_path, matched_tag)
