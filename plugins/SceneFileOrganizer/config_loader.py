"""Config loader for SceneFileOrganizer.

Reads config.yaml, merges user values over sensible defaults, validates strictly
(rejecting unknown keys), and exposes a typed Config dataclass hierarchy.

Generates a commented default config.yaml on first run when no config file exists.
"""

import copy
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

try:
    import stashapi.log as log
except ImportError:
    # Allow tests to run without stashapi installed by providing a stub
    import logging as _logging

    log = _logging.getLogger("stashapi.log")

# =============================================================================
# DEFAULT CONFIG VALUES
# =============================================================================
# Nested dict containing ALL config sections with their default values.
# Matches the DESIGN.md YAML Config Schema exactly (minus process: section).

DEFAULTS: Dict = {
    "filename": {
        "tag_templates": {},
        "studio_templates": {},
        "use_default": False,
        "default": "$date $title",
    },
    "path": {
        "tag_templates": {},
        "studio_templates": {},
        "path_templates": {},
        "use_default": False,
        "default": "^*/$performer",
        "non_organized": "",
    },
    "tag_options": {},
    "text": {
        "space_char": " ",
        "field_whitespace_separator": "",
        "field_replacer": {},
        "word_replacer": {},
        "remove_chars": ",#",
        "lowercase": False,
        "titlecase": False,
        "prepositions_removal": False,
        "prepositions": ["a", "an", "the", "of", "in", "on", "at", "for", "to", "and", "but", "or"],
        "use_ascii": False,
    },
    "formatting": {
        "date_format": "%Y-%m-%d",
        "duration_format": "",
        "rating_format": "{}",
    },
    "performers": {
        "separator": " ",
        "limit": 3,
        "keep_up_to_limit": False,
        "sort": "id",
        "ignore_gender": [],
        "prevent_title_duplicate": False,
    },
    "studios": {
        "squeeze_names": False,
        "max_hierarchy_depth": 0,
    },
    "tags": {
        "separator": " ",
        "whitelist": [],
        "blacklist": [],
    },
    "paths": {
        "prevent_consecutive_folders": True,
        "remove_empty_folders": True,
        "single_performer_in_path": True,
        "keep_existing_performer_folder": True,
        "no_performer_folder": False,
        "max_length": 240,
        "length_reduction_order": [
            "$video_codec",
            "$audio_codec",
            "$resolution",
            "$tags",
            "$rating",
            "$height",
            "$studio_family",
            "$studio",
            "$parent_studio",
            "$performer",
        ],
    },
    "files": {
        "associated_extensions": ["srt", "vtt", "funscript"],
        "duplicate_suffixes": ["", "_1", "_2", "_3", "_4", "_5"],
        "max_duplicate_retries": 99,
        "filename_as_title": False,
    },
    "exclusions": {
        "tags": [],
        "studios": [],
        "paths": [],
    },
    "general": {
        "log_file": "",
        "debug": False,
        "bulk_delay": 1,
    },
}

# Valid top-level section names for strict validation
VALID_SECTIONS = frozenset(DEFAULTS.keys())


# =============================================================================
# DEEP MERGE
# =============================================================================


def deep_merge(base: dict, override: dict) -> dict:
    """Recursively merge override dict into a deep copy of base dict.

    For nested dicts, recurse. For all other types, override wins.
    Does NOT mutate either argument.

    Args:
        base: Base dict with default values.
        override: Override dict with user-provided values.

    Returns:
        A new dict with override values merged over base defaults.
    """
    result = copy.deepcopy(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = deep_merge(result[key], value)
        else:
            result[key] = copy.deepcopy(value)
    return result


# =============================================================================
# CONFIG DATACLASSES
# =============================================================================


@dataclass
class FilenameConfig:
    """Filename template configuration."""

    tag_templates: Dict[str, str] = field(default_factory=dict)
    studio_templates: Dict[str, str] = field(default_factory=dict)
    use_default: bool = False
    default: str = "$date $title"


@dataclass
class PathConfig:
    """Path template configuration."""

    tag_templates: Dict[str, str] = field(default_factory=dict)
    studio_templates: Dict[str, str] = field(default_factory=dict)
    path_templates: Dict[str, str] = field(default_factory=dict)
    use_default: bool = False
    default: str = "^*/$performer"
    non_organized: str = ""


@dataclass
class TextConfig:
    """Text processing configuration."""

    space_char: str = " "
    field_whitespace_separator: str = ""
    field_replacer: Dict[str, str] = field(default_factory=dict)
    word_replacer: Dict[str, Any] = field(default_factory=dict)
    remove_chars: str = ",#"
    lowercase: bool = False
    titlecase: bool = False
    prepositions_removal: bool = False
    prepositions: List[str] = field(default_factory=lambda: ["a", "an", "the", "of", "in", "on", "at", "for", "to", "and", "but", "or"])
    use_ascii: bool = False


@dataclass
class FormattingConfig:
    """Date, duration, and rating formatting configuration."""

    date_format: str = "%Y-%m-%d"
    duration_format: str = ""
    rating_format: str = "{}"


@dataclass
class PerformerConfig:
    """Performer display configuration."""

    separator: str = " "
    limit: int = 3
    keep_up_to_limit: bool = False
    sort: str = "id"
    ignore_gender: List[str] = field(default_factory=list)
    prevent_title_duplicate: bool = False


@dataclass
class StudioConfig:
    """Studio display configuration."""

    squeeze_names: bool = False
    max_hierarchy_depth: int = 0


@dataclass
class TagConfig:
    """Tag filtering configuration."""

    separator: str = " "
    whitelist: List[str] = field(default_factory=list)
    blacklist: List[str] = field(default_factory=list)


@dataclass
class TagModifiers:
    """Per-tag behavior modifiers for tag_options entries.

    Each field defaults to False; users only specify what they want enabled.
    """

    clean_tag: bool = False
    inverse_performer: bool = False
    dry_run: bool = False


# Valid modifier keys for tag_options entries (sorted for consistent error messages)
_VALID_TAG_MODIFIER_KEYS = frozenset(("clean_tag", "inverse_performer", "dry_run"))


@dataclass
class PathManagementConfig:
    """Path management and length configuration."""

    prevent_consecutive_folders: bool = True
    remove_empty_folders: bool = True
    single_performer_in_path: bool = True
    keep_existing_performer_folder: bool = True
    no_performer_folder: bool = False
    max_length: int = 240
    length_reduction_order: List[str] = field(
        default_factory=lambda: [
            "$video_codec",
            "$audio_codec",
            "$resolution",
            "$tags",
            "$rating",
            "$height",
            "$studio_family",
            "$studio",
            "$parent_studio",
            "$performer",
        ]
    )


@dataclass
class FileConfig:
    """File handling configuration."""

    associated_extensions: List[str] = field(
        default_factory=lambda: ["srt", "vtt", "funscript"]
    )
    duplicate_suffixes: List[str] = field(
        default_factory=lambda: ["", "_1", "_2", "_3", "_4", "_5"]
    )
    max_duplicate_retries: int = 99
    filename_as_title: bool = False


@dataclass
class ExclusionConfig:
    """Exclusion pattern configuration."""

    tags: List[str] = field(default_factory=list)
    studios: List[str] = field(default_factory=list)
    paths: List[str] = field(default_factory=list)


@dataclass
class GeneralConfig:
    """General plugin configuration."""

    log_file: str = ""
    debug: bool = False
    bulk_delay: int = 1


@dataclass
class Config:
    """Top-level configuration containing all config sections."""

    filename: FilenameConfig = field(default_factory=FilenameConfig)
    path: PathConfig = field(default_factory=PathConfig)
    tag_options: Dict[str, TagModifiers] = field(default_factory=dict)
    text: TextConfig = field(default_factory=TextConfig)
    formatting: FormattingConfig = field(default_factory=FormattingConfig)
    performers: PerformerConfig = field(default_factory=PerformerConfig)
    studios: StudioConfig = field(default_factory=StudioConfig)
    tags: TagConfig = field(default_factory=TagConfig)
    paths: PathManagementConfig = field(default_factory=PathManagementConfig)
    files: FileConfig = field(default_factory=FileConfig)
    exclusions: ExclusionConfig = field(default_factory=ExclusionConfig)
    general: GeneralConfig = field(default_factory=GeneralConfig)

    @classmethod
    def from_dict(cls, data: dict) -> "Config":
        """Construct the full Config hierarchy from a merged dict.

        Each section key maps to its sub-dataclass via **data.get("section_name", {}).
        tag_options entries are converted to TagModifiers dataclass instances.

        Args:
            data: A dict containing all config sections (typically from deep_merge).

        Returns:
            A fully populated Config dataclass instance.
        """
        return cls(
            filename=FilenameConfig(**data.get("filename", {})),
            path=PathConfig(**data.get("path", {})),
            tag_options={
                tag: TagModifiers(**entry) if isinstance(entry, dict) else TagModifiers()
                for tag, entry in data.get("tag_options", {}).items()
            },
            text=TextConfig(**data.get("text", {})),
            formatting=FormattingConfig(**data.get("formatting", {})),
            performers=PerformerConfig(**data.get("performers", {})),
            studios=StudioConfig(**data.get("studios", {})),
            tags=TagConfig(**data.get("tags", {})),
            paths=PathManagementConfig(**data.get("paths", {})),
            files=FileConfig(**data.get("files", {})),
            exclusions=ExclusionConfig(**data.get("exclusions", {})),
            general=GeneralConfig(**data.get("general", {})),
        )


# =============================================================================
# VALIDATION
# =============================================================================

# Sections whose sub-keys are validated (dicts with known schema).
# tag_options has its own schema-aware validation via _validate_tag_options_schema.
_VALIDATED_SECTIONS = frozenset(
    k for k, v in DEFAULTS.items() if isinstance(v, dict) and k != "tag_options"
)


def _validate_tag_options_schema(tag_options: dict) -> List[str]:
    """Validate tag_options entries for schema correctness.

    Checks that each tag_options entry is a dict with only valid modifier keys
    and boolean values. Collects all errors before returning.

    Args:
        tag_options: The tag_options dict from user config.

    Returns:
        A list of error message strings. Empty list if valid.
    """
    errors: List[str] = []
    valid_keys_str = ", ".join(sorted(_VALID_TAG_MODIFIER_KEYS))

    for tag_name, entry in tag_options.items():
        # Each entry must be a dict
        if not isinstance(entry, dict):
            errors.append(
                f"tag_options['{tag_name}']: expected dict, "
                f"got {type(entry).__name__}"
            )
            continue

        # Validate each key/value in the entry
        for key, value in entry.items():
            if key not in _VALID_TAG_MODIFIER_KEYS:
                errors.append(
                    f"tag_options['{tag_name}']: unknown key '{key}'. "
                    f"Valid keys: {valid_keys_str}"
                )
            elif not isinstance(value, bool):
                errors.append(
                    f"tag_options['{tag_name}'].{key}: expected bool, "
                    f"got {type(value).__name__} ({value!r})"
                )

    return errors


def validate_config(user_config: dict) -> List[str]:
    """Validate user config for unknown or invalid keys.

    Checks top-level sections, nested keys within known sections, and
    tag_options schema (modifier keys and value types).

    Args:
        user_config: The raw dict parsed from config.yaml.

    Returns:
        A list of error message strings. Empty list if valid.
    """
    errors: List[str] = []

    # Check that user_config is a dict
    if not isinstance(user_config, dict):
        return [
            "config.yaml must be a YAML mapping (dict), not a scalar or list."
        ]

    # Check for unknown top-level keys
    unknown_top = set(user_config.keys()) - VALID_SECTIONS
    if unknown_top:
        errors.append(
            f"Unknown config sections: {sorted(unknown_top)}. "
            f"Valid sections are: {sorted(VALID_SECTIONS)}"
        )
        return errors

    # Validate nested unknown keys for each section with a known schema
    for section in _VALIDATED_SECTIONS:
        if section not in user_config:
            continue
        section_data = user_config[section]
        if not isinstance(section_data, dict):
            continue
        valid_keys = set(DEFAULTS[section].keys())
        unknown_nested = set(section_data.keys()) - valid_keys
        if unknown_nested:
            errors.append(
                f"Unknown keys in '{section}': {sorted(unknown_nested)}. "
                f"Valid keys are: {sorted(valid_keys)}"
            )

    # Validate tag_options schema (unknown modifier keys, wrong types, non-dict entries)
    if "tag_options" in user_config and isinstance(user_config["tag_options"], dict):
        errors.extend(_validate_tag_options_schema(user_config["tag_options"]))

    return errors


# =============================================================================
# DEFAULT CONFIG YAML (for generation)
# =============================================================================

DEFAULT_CONFIG_YAML = """\
# =============================================================================
# SceneFileOrganizer Configuration
# =============================================================================
# Edit this file to customize how scenes are renamed and organized.
# The plugin ships disabled with dry-run ON -- you must explicitly enable it.
# Documentation: https://github.com/stashapp/CommunityScripts
# =============================================================================

# ---------------------------------------------------------------------------
#  FILENAME TEMPLATES (what the file is named)
# ---------------------------------------------------------------------------
# Priority: tag_templates > studio_templates > default
# Group syntax: {$var text} -- entire group removed if $var is empty
#
# Available variables:
#   $title, $date, $year, $performer, $studio, $parent_studio,
#   $studio_family, $studio_hierarchy, $studio_code, $rating,
#   $height, $resolution, $duration, $bitrate, $tags,
#   $video_codec, $audio_codec, $oshash, $checksum,
#   $movie_title, $movie_year, $movie_scene,
#   $stashid_scene, $stashid_performer, $date_format

filename:
  # Tag-based templates (highest priority). Key = tag name, value = template.
  tag_templates: {}
    # Example:
    # "!1. Western": "$date $performer - $title [$studio]"
    # "!1. JAV": "$title"

  # Studio-based templates. Key = studio name, value = template.
  studio_templates: {}
    # Example:
    # "Deeper": "[$studio] $title"

  # Whether to apply the default template when no tag/studio template matches.
  use_default: false

  # Default filename template (used when use_default is true and no other matches).
  default: "$date $title"

# ---------------------------------------------------------------------------
#  PATH TEMPLATES (where the file is moved)
# ---------------------------------------------------------------------------
# Priority: tag_templates > studio_templates > path_templates > default
# Special: $studio_hierarchy expands to nested folders
# Special: ^* = current parent directory

path:
  tag_templates: {}
  studio_templates: {}
  # Path-match templates. Key = source path pattern, value = destination template.
  path_templates: {}
  use_default: false
  default: "^*/$performer"
  # Where to move scenes that are un-organized (organized set to false).
  # Leave empty to skip moving un-organized scenes.
  non_organized: ""

# ---------------------------------------------------------------------------
#  TAG OPTIONS (per-tag behavior modifiers)
# ---------------------------------------------------------------------------
# Each key is a tag name. Values are dicts with options:
#   clean_tag: true/false -- remove the tag from scene after processing
#   inverse_performer: true/false -- use "Last First" order for performers
#   dry_run: true/false -- override dry-run setting for scenes with this tag

tag_options: {}
  # Example:
  # "!1. Western":
  #   clean_tag: true
  #   inverse_performer: false

# ---------------------------------------------------------------------------
#  TEXT PROCESSING
# ---------------------------------------------------------------------------

text:
  # Character to replace spaces with in filenames/paths.
  space_char: " "

  # Separator inserted between fields that produce whitespace.
  field_whitespace_separator: ""

  # Per-field character replacements. Key = field variable, value = replacement map.
  field_replacer: {}

  # Word-level replacements applied to all text.
  word_replacer: {}

  # Characters to remove from all generated text.
  remove_chars: ",#"

  # Convert all text to lowercase.
  lowercase: false

  # Convert all text to title case.
  titlecase: false

  # Remove common prepositions from text.
  prepositions_removal: false

  # List of prepositions to remove (when prepositions_removal is true).
  prepositions:
    - "a"
    - "an"
    - "the"
    - "of"
    - "in"
    - "on"
    - "at"
    - "for"
    - "to"
    - "and"
    - "but"
    - "or"

  # Transliterate non-ASCII characters to ASCII equivalents (requires unidecode).
  use_ascii: false

# ---------------------------------------------------------------------------
#  DATE & DURATION FORMATTING
# ---------------------------------------------------------------------------

formatting:
  # Python strftime format for dates.
  date_format: "%Y-%m-%d"

  # Format string for duration (e.g., "%H:%M:%S"). Empty = raw minutes.
  duration_format: ""

  # Format string for rating (e.g., "{}/5", "{:.1f}"). {} = raw value.
  rating_format: "{}"

# ---------------------------------------------------------------------------
#  PERFORMER OPTIONS
# ---------------------------------------------------------------------------

performers:
  # Separator between multiple performer names.
  separator: " "

  # Maximum number of performers to include in filename/path.
  limit: 3

  # If true, always include up to limit performers even in paths.
  keep_up_to_limit: false

  # Sort order for performers: "id", "name", "rating", "favorite", "mix", "mixid"
  sort: "id"

  # List of genders to exclude from performer list.
  ignore_gender: []

  # If true, omit performer name from filename when it duplicates the title.
  prevent_title_duplicate: false

# ---------------------------------------------------------------------------
#  STUDIO OPTIONS
# ---------------------------------------------------------------------------

studios:
  # Remove spaces from studio names (e.g., "Vixen Media" -> "VixenMedia").
  squeeze_names: false

  # Max depth for $studio_hierarchy. 0 = unlimited.
  max_hierarchy_depth: 0

# ---------------------------------------------------------------------------
#  TAG OPTIONS (for $tags variable)
# ---------------------------------------------------------------------------

tags:
  # Separator between multiple tag names.
  separator: " "

  # Only include these tags in $tags variable (empty = all tags).
  whitelist: []

  # Exclude these tags from $tags variable.
  blacklist: []

# ---------------------------------------------------------------------------
#  PATH MANAGEMENT
# ---------------------------------------------------------------------------

paths:
  # Prevent duplicate consecutive folder names in path.
  prevent_consecutive_folders: true

  # Remove empty source folders after moving files.
  remove_empty_folders: true

  # Use only one performer in path (even if multiple in filename).
  single_performer_in_path: true

  # Keep existing performer folder if scene is already in one.
  keep_existing_performer_folder: true

  # Skip performer folder entirely if no performer is found.
  no_performer_folder: false

  # Maximum total path length (including filename).
  max_length: 240

  # Order in which fields are removed to reduce path length.
  length_reduction_order:
    - "$video_codec"
    - "$audio_codec"
    - "$resolution"
    - "$tags"
    - "$rating"
    - "$height"
    - "$studio_family"
    - "$studio"
    - "$parent_studio"
    - "$performer"

# ---------------------------------------------------------------------------
#  FILE HANDLING
# ---------------------------------------------------------------------------

files:
  # Associated file extensions to move alongside video files.
  associated_extensions:
    - "srt"
    - "vtt"
    - "funscript"

  # Suffixes to try when checking for duplicate filenames.
  duplicate_suffixes:
    - ""
    - "_1"
    - "_2"
    - "_3"
    - "_4"
    - "_5"

  # Maximum number of duplicate suffix retries before giving up (0 = unlimited).
  # max_duplicate_retries: 99

  # Use the filename (without extension) as scene title if title is empty.
  filename_as_title: false

# ---------------------------------------------------------------------------
#  EXCLUSIONS (scenes matching these patterns are skipped)
# ---------------------------------------------------------------------------

exclusions:
  # Tags that cause a scene to be skipped.
  tags: []

  # Studios that cause a scene to be skipped.
  studios: []

  # Path patterns that cause a scene to be skipped.
  paths: []

# ---------------------------------------------------------------------------
#  GENERAL
# ---------------------------------------------------------------------------

general:
  # Path to a log file for rename operations. Empty = no file logging.
  log_file: ""

  # Enable debug-level logging.
  debug: false

  # Delay in seconds between bulk/backfill operations (prevents database locking).
  bulk_delay: 1
"""


# =============================================================================
# DEFAULT CONFIG GENERATION
# =============================================================================


def generate_default_config(config_path: str) -> None:
    """Write the default config YAML to disk.

    Args:
        config_path: Absolute path where config.yaml should be written.
    """
    try:
        with open(config_path, "w") as f:
            f.write(DEFAULT_CONFIG_YAML)
    except (IOError, OSError) as e:
        log.error(f"Failed to write default config to {config_path}: {e}")


# =============================================================================
# LOAD CONFIG
# =============================================================================


def load_config(plugin_dir: str) -> Optional[Config]:
    """Load and validate configuration from config.yaml.

    If config.yaml does not exist, generates a commented default and returns None.
    If config.yaml is malformed or has unknown keys, logs errors and returns None.

    Args:
        plugin_dir: Path to the plugin directory containing config.yaml.

    Returns:
        A Config dataclass instance, or None if config is missing/invalid.
    """
    config_path = os.path.join(plugin_dir, "config.yaml")

    # Generate default config if file does not exist
    if not os.path.exists(config_path):
        generate_default_config(config_path)
        log.info(
            "Generated default config.yaml. "
            "Please edit it and re-enable the plugin."
        )
        return None

    # Read and parse YAML
    try:
        with open(config_path, "r") as f:
            user_config = yaml.safe_load(f)
    except yaml.YAMLError as e:
        log.error(f"Failed to parse config.yaml: {e}")
        return None

    # Handle empty file (yaml.safe_load returns None for empty YAML)
    if user_config is None:
        user_config = {}

    # Check it is a dict
    if not isinstance(user_config, dict):
        log.error(
            "config.yaml must be a YAML mapping (dict), "
            f"not {type(user_config).__name__}."
        )
        return None

    # Validate for unknown keys
    errors = validate_config(user_config)
    if errors:
        for error in errors:
            log.error(f"Config validation error: {error}")
        return None

    # Merge with defaults
    merged = deep_merge(DEFAULTS, user_config)

    # Warn about empty and orphan tag_options entries (non-fatal)
    tag_options_raw = merged.get("tag_options", {})
    if isinstance(tag_options_raw, dict) and tag_options_raw:
        filename_templates = merged.get("filename", {}).get("tag_templates", {})
        path_templates = merged.get("path", {}).get("tag_templates", {})
        for tag_name, entry in tag_options_raw.items():
            if isinstance(entry, dict) and len(entry) == 0:
                log.warning(
                    f"tag_options['{tag_name}']: entry has no modifiers "
                    f"and will have no effect"
                )
            if tag_name not in filename_templates and tag_name not in path_templates:
                log.warning(
                    f"tag_options['{tag_name}']: no matching tag_template "
                    f"found in filename or path templates"
                )

    # Build Config dataclass
    try:
        config = Config.from_dict(merged)
    except (TypeError, ValueError) as e:
        log.error(f"Failed to build config from merged values: {e}")
        return None

    return config
