"""Metadata extraction for SceneFileOrganizer.

Provides the public ``extract_metadata(scene, config)`` entry point that
transforms a Stash scene data dict into a flat ``dict[str, str]`` of 25+
template variables.  Delegates to focused private helpers for each domain
(dates, performers, studios, tags, technical fields, groups, stash IDs).

Every function returns ``str`` or ``dict[str, str]`` -- never ``None``.
All values are null-safe via ``_safe_str()`` and ``dict.get()`` with defaults.
The module is pure (no I/O, no Stash connection) and uses only stdlib.
"""

import re
import time
from datetime import datetime

from config_loader import (
    Config,
    FormattingConfig,
    PerformerConfig,
    StudioConfig,
    TagConfig,
)


# =============================================================================
# TEMPLATE VARIABLES REFERENCE
# =============================================================================

TEMPLATE_VARIABLES: dict = {
    # Scene metadata
    "title": "",
    "date": "",
    "year": "",
    "date_format": "",
    "rating": "",
    # Performers
    "performer": "",
    "stashid_performer": "",
    # Studio
    "studio": "",
    "parent_studio": "",
    "studio_family": "",
    "studio_hierarchy": "",
    "studio_code": "",
    # Tags
    "tags": "",
    # Technical (from first file)
    "height": "",
    "resolution": "",
    "duration": "",
    "bitrate": "",
    "video_codec": "",
    "audio_codec": "",
    # Fingerprints
    "oshash": "",
    "checksum": "",
    # Movies/Groups
    "movie_title": "",
    "movie_year": "",
    "movie_scene": "",
    # Stash IDs
    "stashid_scene": "",
}


# =============================================================================
# NULL-SAFE UTILITIES
# =============================================================================


def _safe_str(value) -> str:
    """Convert any value to string, treating None as empty string.

    No function returns None in any value position.
    """
    if value is None:
        return ""
    return str(value)


def _get_nested(data: dict, *keys, default="") -> str:
    """Safely traverse nested dicts, returning default if any key is missing.

    Each intermediate value must be a dict for traversal to continue.
    The final value is converted to str via str(). Returns default if any
    key is missing or an intermediate value is not a dict.
    """
    current = data
    for key in keys:
        if not isinstance(current, dict):
            return default
        current = current.get(key)
        if current is None:
            return default
    return str(current) if current is not None else default


# =============================================================================
# FINGERPRINT EXTRACTION
# =============================================================================


def _get_fingerprint(scene: dict, fp_type: str) -> str:
    """Extract a fingerprint value from the first file's fingerprints array.

    The scene dict from stashapp-tools nests fingerprints under
    files[].fingerprints[]. Each fingerprint has {type: str, value: str}.

    Also checks for flattened fingerprint keys on the file dict as a fallback
    (stashapp-tools may flatten these, e.g., files[0].get("oshash")).

    Returns "" if not found.
    """
    files = scene.get("files") or []
    if not files:
        return ""

    first_file = files[0]

    # Check nested fingerprints array first (preferred)
    fingerprints = first_file.get("fingerprints") or []
    for fp in fingerprints:
        if fp.get("type") == fp_type:
            return _safe_str(fp.get("value"))

    # Fallback: check for flattened fingerprint keys on file dict
    direct = first_file.get(fp_type)
    if direct:
        return _safe_str(direct)

    return ""


# =============================================================================
# DATE PARSING
# =============================================================================


def _extract_date_fields(date_str: str, formatting: FormattingConfig) -> dict:
    """Parse date string with multi-format fallback.

    Handles: "2024-01-15" (full ISO), "2024" (year-only), "" (empty),
    and malformed strings. Never raises exceptions.

    Returns dict with keys: year, date_format. All values are strings.
    """
    result = {"year": "", "date_format": ""}

    if not date_str:
        return result

    # Try full ISO date first
    try:
        dt = datetime.strptime(date_str, "%Y-%m-%d")
        result["year"] = str(dt.year)
        result["date_format"] = dt.strftime(formatting.date_format)
        return result
    except ValueError:
        pass

    # Try year-only extraction (first 4 chars if digits)
    if len(date_str) >= 4 and date_str[:4].isdigit():
        result["year"] = date_str[:4]

    return result


# =============================================================================
# RESOLUTION MAPPING
# =============================================================================


def _map_resolution(height: int, width: int) -> tuple:
    """Map pixel dimensions to (height_label, resolution_category).

    Vertical detection: height > width produces VERTICAL category.
    Thresholds checked from highest to lowest.

    Returns: (height_label: str, resolution_category: str)
    """
    # Vertical video detection
    if height > width:
        return (f"{height}p", "VERTICAL")

    # Standard mappings (check highest first)
    if height >= 4320:
        return ("8k", "UHD")
    if height >= 3384:
        return ("6k", "UHD")
    if height >= 2880:
        return ("5k", "UHD")
    if height >= 2160:
        return ("4k", "UHD")
    if height >= 720:
        return (f"{height}p", "HD")

    return (f"{height}p", "SD")


# =============================================================================
# RATING FORMATTING
# =============================================================================


def _format_rating(rating100, formatting: FormattingConfig) -> str:
    """Format rating100 int using formatting.rating_format.

    Returns "" if rating100 is None. Uses rating_format.format(rating100)
    for the value.
    """
    if rating100 is None:
        return ""
    return formatting.rating_format.format(rating100)


# =============================================================================
# GROUPS/MOVIES EXTRACTION
# =============================================================================


def _extract_groups(scene: dict) -> dict:
    """Extract movie/group template variables with backward compatibility.

    Checks scene.get("groups") first (Stash v0.27+), falls back to
    scene.get("movies") (v0.26-). For first entry, checks entry.get("group")
    first, falls back to entry.get("movie").

    Returns dict with keys: movie_title, movie_year, movie_scene.
    All values are strings.
    """
    # Try new field name first, fall back to old
    group_entries = scene.get("groups") or scene.get("movies") or []

    variables = {"movie_title": "", "movie_year": "", "movie_scene": ""}
    if not group_entries:
        return variables

    first = group_entries[0]
    # New schema: first["group"]["name"], Old schema: first["movie"]["name"]
    group_data = first.get("group") or first.get("movie") or {}

    variables["movie_title"] = _safe_str(group_data.get("name"))
    date = group_data.get("date") or ""
    variables["movie_year"] = date[:4] if len(date) >= 4 else ""

    scene_index = first.get("scene_index")
    if scene_index is not None:
        variables["movie_scene"] = f"scene {scene_index}"

    return variables


# =============================================================================
# TAG EXTRACTION
# =============================================================================


def _extract_tags(tags: list, config: TagConfig) -> dict:
    """Filter tags list by whitelist/blacklist and join remaining tag names.

    Whitelist: if non-empty, only include tags whose name is in whitelist.
    Blacklist: exclude tags whose name is in blacklist (applied after whitelist).
    Join remaining names with config.separator.

    Returns dict with key: tags. Value is a string.
    """
    if not tags:
        return {"tags": ""}

    # Extract names
    names = [t.get("name", "") for t in tags]

    # Whitelist filter (only if whitelist is non-empty)
    if config.whitelist:
        whitelist_set = set(config.whitelist)
        names = [n for n in names if n in whitelist_set]

    # Blacklist filter
    if config.blacklist:
        blacklist_set = set(config.blacklist)
        names = [n for n in names if n not in blacklist_set]

    return {"tags": config.separator.join(names)}


# =============================================================================
# STASH ID EXTRACTION
# =============================================================================


def _extract_stash_ids(scene: dict, variables: dict) -> dict:
    """Extract scene stash ID from stash_ids array.

    Takes the first stash_id from scene.get("stash_ids", []). The
    stashid_performer is handled by performer extraction.

    Returns dict with key: stashid_scene. Value is a string.
    """
    stash_ids = scene.get("stash_ids") or []
    stashid_scene = ""
    if stash_ids:
        stashid_scene = _safe_str(stash_ids[0].get("stash_id", ""))

    return {"stashid_scene": stashid_scene}


# =============================================================================
# TECHNICAL FIELD EXTRACTION
# =============================================================================


def _extract_technical(scene: dict) -> dict:
    """Extract technical video fields from the first file in the scene.

    From scene.get("files", [{}])[0], extracts: video_codec (uppercase),
    audio_codec (uppercase), duration (raw float to string), bitrate
    (divide by 1_000_000, round to 2 decimals). Calls _map_resolution()
    for height/width.

    Returns dict with keys: height, resolution, duration, bitrate,
    video_codec, audio_codec. All values are strings, "" if missing.
    """
    result = {
        "height": "",
        "resolution": "",
        "duration": "",
        "bitrate": "",
        "video_codec": "",
        "audio_codec": "",
    }

    files = scene.get("files") or []
    if not files:
        return result

    first_file = files[0]

    # Video/audio codecs (uppercase)
    video_codec = first_file.get("video_codec")
    if video_codec:
        result["video_codec"] = str(video_codec).upper()

    audio_codec = first_file.get("audio_codec")
    if audio_codec:
        result["audio_codec"] = str(audio_codec).upper()

    # Duration (raw float to string)
    duration = first_file.get("duration")
    if duration is not None:
        result["duration"] = str(duration)

    # Bitrate (bps -> Mbps, rounded to 2 decimals)
    bit_rate = first_file.get("bit_rate")
    if bit_rate is not None:
        result["bitrate"] = str(round(int(bit_rate) / 1_000_000, 2))

    # Resolution
    file_height = first_file.get("height")
    file_width = first_file.get("width")
    if file_height is not None and file_width is not None:
        height_label, res_category = _map_resolution(file_height, file_width)
        result["height"] = height_label
        result["resolution"] = res_category

    return result


# =============================================================================
# PERFORMER SORTING AND EXTRACTION
# =============================================================================


def _sort_performers(performers: list, sort_mode: str) -> list:
    """Sort performer dicts by the specified mode with deterministic ID tiebreaker.

    Sort modes:
    - "id": numeric ascending by performer ID
    - "name": alphabetical by name, ID tiebreaker
    - "rating": highest rating100 first, then name alpha, then ID
    - "favorite": favorites first, then name alpha, then ID
    - "mix": favorites first, then rating desc, then name alpha, then ID
    - "mixid": favorites first, then rating desc, then ID (no name sort)

    Returns the sorted list. Unrecognized sort_mode returns list as-is.
    """
    if sort_mode == "id":
        return sorted(performers, key=lambda p: int(p.get("id", "0")))
    elif sort_mode == "name":
        return sorted(
            performers,
            key=lambda p: (p.get("name", ""), int(p.get("id", "0"))),
        )
    elif sort_mode == "rating":
        return sorted(
            performers,
            key=lambda p: (
                -(p.get("rating100") or 0),
                p.get("name", ""),
                int(p.get("id", "0")),
            ),
        )
    elif sort_mode == "favorite":
        return sorted(
            performers,
            key=lambda p: (
                not p.get("favorite", False),
                p.get("name", ""),
                int(p.get("id", "0")),
            ),
        )
    elif sort_mode == "mix":
        return sorted(
            performers,
            key=lambda p: (
                not p.get("favorite", False),
                -(p.get("rating100") or 0),
                p.get("name", ""),
                int(p.get("id", "0")),
            ),
        )
    elif sort_mode == "mixid":
        return sorted(
            performers,
            key=lambda p: (
                not p.get("favorite", False),
                -(p.get("rating100") or 0),
                int(p.get("id", "0")),
            ),
        )
    return performers


def _extract_performers(performers: list, config: PerformerConfig) -> dict:
    """Extract performer template variables with sort, filter, and limit.

    Steps:
    1. Return empty strings if no performers.
    2. Filter by gender (ignore_gender config).
    3. Sort by configured sort mode.
    4. Apply limit (truncate or empty based on keep_up_to_limit).
    5. Join names and stash IDs with separator.

    Returns dict with keys: performer, stashid_performer.
    """
    result = {"performer": "", "stashid_performer": ""}

    if not performers:
        return result

    # Gender filtering
    filtered = performers
    if config.ignore_gender:
        ignore_set = set(config.ignore_gender)
        filtered = [
            p
            for p in performers
            if p.get("gender") not in ignore_set
            and not (p.get("gender") is None and "UNDEFINED" in ignore_set)
        ]

    # Sort
    sorted_perfs = _sort_performers(filtered, config.sort)

    # Limit enforcement
    if len(sorted_perfs) > config.limit:
        if config.keep_up_to_limit:
            sorted_perfs = sorted_perfs[: config.limit]
        else:
            sorted_perfs = []

    # Build name string
    names = [p.get("name", "") for p in sorted_perfs]
    result["performer"] = config.separator.join(names)

    # Build stash ID string
    stash_ids = []
    for p in sorted_perfs:
        p_stash_ids = p.get("stash_ids") or []
        if p_stash_ids:
            stash_ids.append(p_stash_ids[0].get("stash_id", ""))
    result["stashid_performer"] = config.separator.join(stash_ids)

    return result


# =============================================================================
# PERFORMER NAME INVERSION
# =============================================================================


def _invert_performer_names(performer_str: str, separator: str = " ") -> str:
    """Invert performer name format from 'Last, First' to 'First Last'.

    Each performer name in the separator-joined string is individually
    inverted. Names without a comma are left unchanged.

    When the separator is a space, splitting is ambiguous (spaces appear
    within "Last, First" names). In that case a regex replaces each
    ``word, word`` pattern in-place rather than splitting.

    Args:
        performer_str: Separator-joined performer names (e.g., "Doe, Jane Smith, John").
        separator: The separator used between multiple performer names.

    Returns:
        Separator-joined string with each name inverted.
    """
    if not performer_str:
        return ""

    if separator == " ":
        # Space separator: use regex to find and invert "Last, First" patterns
        # without splitting (which would break within multi-word names).
        return re.sub(
            r"(\S+), (\S+)",
            lambda m: f"{m.group(2)} {m.group(1)}",
            performer_str,
        )

    # Non-space separator: split, invert each, rejoin
    names = performer_str.split(separator)
    inverted = []
    for name in names:
        if ", " in name:
            parts = name.split(", ", 1)
            inverted.append(f"{parts[1]} {parts[0]}")
        else:
            inverted.append(name)
    return separator.join(inverted)


# =============================================================================
# STUDIO HIERARCHY AND EXTRACTION
# =============================================================================


def _build_studio_hierarchy(studio, max_depth: int) -> list:
    """Walk parent_studio chain, collect names, detect cycles via visited set.

    Traverses from the given studio up through parent_studio links, collecting
    studio names. Uses a visited set of studio IDs to detect circular references.
    Respects max_depth cap (0 = unlimited).

    Returns list of studio names in root-to-leaf order (reversed after traversal).
    Returns empty list for falsy/empty studio input.
    """
    if not studio:
        return []

    hierarchy = []
    visited = set()
    current = studio
    depth = 0

    while current:
        studio_id = current.get("id")
        if studio_id in visited:
            break  # Circular reference detected
        visited.add(studio_id)
        hierarchy.append(current.get("name", ""))

        depth += 1
        if max_depth > 0 and depth >= max_depth:
            break

        current = current.get("parent_studio")

    hierarchy.reverse()  # Convert leaf-to-root to root-to-leaf order
    return hierarchy


def _extract_studio(studio, config: StudioConfig) -> dict:
    """Extract studio template variables from the studio dict.

    Produces: studio, parent_studio, studio_family, studio_hierarchy.
    Applies squeeze_names (remove spaces) when config.squeeze_names is True.
    Uses _build_studio_hierarchy for hierarchy traversal with cycle detection
    and depth cap.

    Returns dict with keys: studio, parent_studio, studio_family, studio_hierarchy.
    All values are strings.
    """
    result = {
        "studio": "",
        "parent_studio": "",
        "studio_family": "",
        "studio_hierarchy": "",
    }

    if not studio:
        return result

    # Get studio name
    studio_name = studio.get("name", "")
    if config.squeeze_names:
        studio_name = studio_name.replace(" ", "")
    result["studio"] = studio_name

    # Get parent_studio name
    parent_name = _get_nested(studio, "parent_studio", "name")
    if config.squeeze_names and parent_name:
        parent_name = parent_name.replace(" ", "")
    result["parent_studio"] = parent_name

    # Build hierarchy
    hierarchy = _build_studio_hierarchy(studio, config.max_hierarchy_depth)
    if config.squeeze_names:
        hierarchy = [name.replace(" ", "") for name in hierarchy]

    # studio_family: root (first element) of hierarchy, or studio name if single
    if hierarchy:
        result["studio_family"] = hierarchy[0]
    else:
        result["studio_family"] = studio_name

    # studio_hierarchy: separator-joined string (path builder splits with os.sep)
    result["studio_hierarchy"] = "/".join(hierarchy)

    return result


# =============================================================================
# PUBLIC ENTRY POINT
# =============================================================================


def extract_metadata(scene: dict, config: Config) -> dict:
    """Transform a Stash scene data dict into a flat template variables dict.

    This is the module's public API. Downstream consumers (Phase 5 path
    builder) call this single function to obtain all 25+ string template
    variables needed for filename and path rendering.

    Every value in the returned dict is a ``str`` -- never ``None`` or a
    non-string type. Missing/null fields produce ``""``.

    Args:
        scene: Scene data dict from Stash (via stashapp-tools find_scene).
        config: Fully populated Config dataclass.

    Returns:
        A flat ``dict[str, str]`` with keys matching ``TEMPLATE_VARIABLES``.
    """
    # Start from a copy of the reference dict (all values "")
    variables = dict(TEMPLATE_VARIABLES)

    # ------------------------------------------------------------------
    # Simple scalar fields
    # ------------------------------------------------------------------
    variables["title"] = _safe_str(scene.get("title"))
    variables["studio_code"] = _safe_str(scene.get("code"))

    # ------------------------------------------------------------------
    # Fingerprints
    # ------------------------------------------------------------------
    variables["oshash"] = _get_fingerprint(scene, "oshash")
    variables["checksum"] = _get_fingerprint(scene, "checksum")

    # ------------------------------------------------------------------
    # Date fields
    # ------------------------------------------------------------------
    date_str = _safe_str(scene.get("date"))
    variables["date"] = date_str
    variables.update(_extract_date_fields(date_str, config.formatting))

    # ------------------------------------------------------------------
    # Rating
    # ------------------------------------------------------------------
    variables["rating"] = _format_rating(scene.get("rating100"), config.formatting)

    # ------------------------------------------------------------------
    # Performers
    # ------------------------------------------------------------------
    variables.update(
        _extract_performers(scene.get("performers", []), config.performers)
    )

    # prevent_title_duplicate: clear performer when it matches the title
    if (
        config.performers.prevent_title_duplicate
        and variables["performer"] == variables["title"]
    ):
        variables["performer"] = ""

    # ------------------------------------------------------------------
    # Studio
    # ------------------------------------------------------------------
    variables.update(_extract_studio(scene.get("studio"), config.studios))

    # ------------------------------------------------------------------
    # Tags
    # ------------------------------------------------------------------
    variables.update(_extract_tags(scene.get("tags", []), config.tags))

    # ------------------------------------------------------------------
    # Technical fields
    # ------------------------------------------------------------------
    variables.update(_extract_technical(scene))

    # ------------------------------------------------------------------
    # Groups/Movies
    # ------------------------------------------------------------------
    variables.update(_extract_groups(scene))

    # ------------------------------------------------------------------
    # Stash IDs
    # ------------------------------------------------------------------
    variables.update(_extract_stash_ids(scene, variables))

    # ------------------------------------------------------------------
    # Duration formatting
    # ------------------------------------------------------------------
    if config.formatting.duration_format and variables["duration"]:
        try:
            seconds = float(variables["duration"])
            variables["duration"] = time.strftime(
                config.formatting.duration_format, time.gmtime(seconds)
            )
        except (ValueError, OverflowError):
            pass  # Keep raw string on any error

    # ------------------------------------------------------------------
    # Final safety pass: ensure every value is str
    # ------------------------------------------------------------------
    variables = {k: _safe_str(v) for k, v in variables.items()}

    return variables
