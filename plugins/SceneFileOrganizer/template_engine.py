"""Template engine for SceneFileOrganizer.

Provides priority-based template selection (tag > studio > path-match > default)
for both filename and path templates, plus three-pass template rendering with
group expansion, variable substitution, and empty delimiter cleanup.

Template selection accepts Config sub-dataclasses (FilenameConfig, PathConfig),
not the full Config object, for explicit dependency and testability.

Template rendering uses a three-pass approach:
  Pass 1 (expand_groups): Expand {$var text} conditional groups
  Pass 2 (substitute_variables): Replace $variable placeholders
  Pass 3 (clean_empty_delimiters): Remove empty [] and () left behind

This ordering prevents the delimiter-leaking bug (Issue #101) from the
predecessor renamerOnUpdate plugin, and cleans up empty bracket/paren pairs
when variables outside groups resolve to empty strings.
"""

import re
from typing import Optional

from config_loader import FilenameConfig, PathConfig

# =============================================================================
# COMPILED REGEX PATTERNS (module-level constants, no side effects)
# =============================================================================

# Matches $identifier where identifier starts with [a-z_] and continues with
# [a-z0-9_]. The greedy [a-z0-9_]* ensures longest match at each $ position,
# preventing prefix collision ($studio vs $studio_family).
VAR_PATTERN = re.compile(r"\$([a-z_][a-z0-9_]*)")

# Matches {content} where content does not contain nested }.
# [^}]* stops at the first closing brace (no nesting support by design).
GROUP_PATTERN = re.compile(r"\{([^}]*)\}")

# Matches empty bracket/paren pairs (with optional internal whitespace).
# Used in Pass 3 to clean up delimiters left behind when variables resolve
# to empty strings outside of conditional groups.
EMPTY_DELIMITERS_RE = re.compile(r"\[\s*\]|\(\s*\)")

# Matches runs of two or more whitespace characters, used to collapse
# gaps left after removing empty delimiter pairs.
MULTI_WHITESPACE_RE = re.compile(r"\s{2,}")


# =============================================================================
# TEMPLATE RENDERING
# =============================================================================


def substitute_variables(template: str, variables: dict) -> str:
    """Replace $variable placeholders with values from the variables dict.

    Unknown variables are replaced with empty string, never left as literals.
    The regex naturally matches the longest valid identifier at each $ position,
    preventing prefix collision (e.g., $studio vs $studio_family).

    Args:
        template: Template string containing $variable placeholders.
        variables: Dict mapping variable names (without $) to string values.

    Returns:
        Template with all $variable placeholders replaced.
    """

    def _replace_var(match: re.Match) -> str:
        var_name = match.group(1)
        return variables.get(var_name, "")

    return VAR_PATTERN.sub(_replace_var, template)


def expand_groups(template: str, variables: dict) -> str:
    """Expand {$var text} conditional groups (Pass 1 of two-pass rendering).

    If ANY $variable inside a group resolves to an empty string or is missing,
    the ENTIRE group (including all static text) is removed. Otherwise,
    variables within the group are substituted and the braces are stripped.

    This must run BEFORE substitute_variables to prevent delimiter leaking.

    Args:
        template: Template string containing {group} sections.
        variables: Dict mapping variable names (without $) to string values.

    Returns:
        Template with groups expanded or removed.
    """

    def _replace_group(match: re.Match) -> str:
        group_content = match.group(1)
        vars_in_group = VAR_PATTERN.findall(group_content)
        for var_name in vars_in_group:
            if not variables.get(var_name, ""):
                return ""  # Remove entire group
        # All variables have values -- substitute within group
        return substitute_variables(group_content, variables)

    return GROUP_PATTERN.sub(_replace_group, template)


def clean_empty_delimiters(text: str) -> str:
    """Remove empty bracket/paren pairs and collapse resulting whitespace.

    Handles ``[]``, ``[ ]``, ``()``, ``( )`` left behind when variables
    outside conditional groups resolve to empty strings.

    Args:
        text: Rendered template string that may contain empty delimiters.

    Returns:
        Cleaned string with empty delimiters removed and whitespace normalized.
    """
    text = EMPTY_DELIMITERS_RE.sub("", text)
    text = MULTI_WHITESPACE_RE.sub(" ", text)
    return text.strip()


def render_template(template: str, variables: dict) -> str:
    """Render a template string with three-pass processing.

    Pass 1: Expand {$var text} groups (removes groups with empty variables).
    Pass 2: Substitute remaining $variable placeholders outside groups.
    Pass 3: Clean empty delimiter pairs ([], ()) left by empty variables.

    This ordering prevents the delimiter-leaking bug (Issue #101) and
    ensures clean filenames when variables resolve to empty strings.

    Args:
        template: Template string with $variables and optional {groups}.
        variables: Dict mapping variable names (without $) to string values.

    Returns:
        Fully rendered template string.
    """
    result = expand_groups(template, variables)
    result = substitute_variables(result, variables)
    result = clean_empty_delimiters(result)
    return result


# =============================================================================
# TEMPLATE SELECTION
# =============================================================================


def select_filename_template(
    scene_tags: list,
    scene_studio: str,
    config: FilenameConfig,
) -> Optional[str]:
    """Select the filename template for a scene based on priority chain.

    Priority: tag > studio > default.
    Returns None if no template matches (scene keeps current filename).

    Args:
        scene_tags: List of tag names on the scene.
        scene_studio: Studio name of the scene (may be empty string).
        config: FilenameConfig with tag_templates, studio_templates, etc.

    Returns:
        The selected template string, or None if no match.
    """
    # 1. Tag templates (highest priority)
    for tag in scene_tags:
        if tag in config.tag_templates:
            return config.tag_templates[tag]

    # 2. Studio templates (guard empty string)
    if scene_studio and scene_studio in config.studio_templates:
        return config.studio_templates[scene_studio]

    # 3. Default (only if use_default is True)
    if config.use_default:
        return config.default

    return None


def select_path_template(
    scene_tags: list,
    scene_studio: str,
    current_path: str,
    config: PathConfig,
) -> Optional[str]:
    """Select the path template for a scene based on priority chain.

    Priority: tag > studio > path-match > default.
    Returns None if no template matches (scene keeps current path).

    Path matching uses the ``in`` operator (substring match) for backward
    compatibility with renamerOnUpdate configs where users write partial
    path patterns like ``/stash/videos/unsorted``.

    Args:
        scene_tags: List of tag names on the scene.
        scene_studio: Studio name of the scene (may be empty string).
        current_path: Current file path of the scene.
        config: PathConfig with tag_templates, studio_templates, path_templates, etc.

    Returns:
        The selected template string, or None if no match.
    """
    # 1. Tag templates (highest priority)
    for tag in scene_tags:
        if tag in config.tag_templates:
            return config.tag_templates[tag]

    # 2. Studio templates (guard empty string)
    if scene_studio and scene_studio in config.studio_templates:
        return config.studio_templates[scene_studio]

    # 3. Path-match templates (key is a path substring to match)
    for path_pattern, template in config.path_templates.items():
        if path_pattern in current_path:
            return template

    # 4. Default (only if use_default is True)
    if config.use_default:
        return config.default

    return None
