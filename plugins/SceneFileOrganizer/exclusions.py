"""Exclusion filtering for SceneFileOrganizer.

Checks whether a scene should be skipped based on configured exclusion rules
(tags, studios, paths). Uses OR logic: the first matching rule wins and the
scene is excluded immediately. All matching is case-insensitive for tags and
studios, and uses regex for path patterns.
"""

import re
from dataclasses import dataclass


@dataclass
class ExclusionResult:
    """Result of an exclusion check.

    Attributes:
        excluded: True if the scene matches an exclusion rule.
        reason: Human-readable description of which rule matched
            (e.g., "tag: DoNotRename"). Empty string if not excluded.
    """

    excluded: bool
    reason: str = ""


def check_exclusions(scene: dict, exclusion_config) -> ExclusionResult:
    """Check if a scene matches any exclusion rule. First match wins.

    Check order: tags first, then studio, then paths (per user decision).
    Uses OR logic -- any single match causes the scene to be excluded.

    Args:
        scene: A scene dict in GraphQL shape (with tags, studio, files keys).
        exclusion_config: An ExclusionConfig instance from config_loader
            with ``tags``, ``studios``, and ``paths`` list attributes.

    Returns:
        ExclusionResult with ``excluded=True`` and a reason string if any
        rule matches, or ``excluded=False`` with empty reason if no match.
    """
    # --- Tag check ---
    if exclusion_config.tags:
        excluded_tags_lower = [t.lower() for t in exclusion_config.tags]
        scene_tags = [t.get("name", "") for t in scene.get("tags", [])]
        for tag_name in scene_tags:
            if tag_name.lower() in excluded_tags_lower:
                return ExclusionResult(True, f"tag: {tag_name}")

    # --- Studio check ---
    if exclusion_config.studios:
        excluded_studios_lower = [s.lower() for s in exclusion_config.studios]
        studio = scene.get("studio") or {}
        studio_name = studio.get("name", "")
        if studio_name and studio_name.lower() in excluded_studios_lower:
            return ExclusionResult(True, f"studio: {studio_name}")

    # --- Path check ---
    if exclusion_config.paths:
        files = scene.get("files") or []
        if files:
            file_path = files[0].get("path", "")
            for pattern in exclusion_config.paths:
                if re.search(pattern, file_path):
                    return ExclusionResult(True, f"path: {pattern}")

    return ExclusionResult(False)
