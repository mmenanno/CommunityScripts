"""GraphQL scene fetching, library path validation, and tag removal for SceneFileOrganizer.

Provides a custom GraphQL fragment with explicit field selection for scene
fetching (instead of the default stashapp-tools introspection fragment that
simplifies nested objects to ``{ id }``), library path querying, path
validation, and tag removal for the clean_tag modifier. All functions accept
``stash`` as a parameter for mock-friendliness.
"""

import os

try:
    import stashapi.log as log
except ImportError:
    # Allow tests to run without stashapi installed by providing a stub
    import logging as _logging

    log = _logging.getLogger("stashapi.log")


# =============================================================================
# GRAPHQL FRAGMENTS
# =============================================================================

# Fragment for Stash v0.27+ (uses ``groups`` field)
SCENE_FRAGMENT = """
    id
    title
    code
    date
    rating100
    organized
    stash_ids { endpoint stash_id }
    files {
        id
        path
        basename
        width
        height
        duration
        video_codec
        audio_codec
        bit_rate
        frame_rate
        fingerprints { type value }
    }
    studio {
        id
        name
        parent_studio {
            id
            name
            parent_studio {
                id
                name
                parent_studio {
                    id
                    name
                    parent_studio { id name }
                }
            }
        }
    }
    tags { id name }
    performers {
        id
        name
        gender
        favorite
        rating100
        stash_ids { endpoint stash_id }
    }
    groups {
        group { name date }
        scene_index
    }
"""

# Fragment for Stash v0.22-v0.26 (uses ``movies`` field instead of ``groups``)
SCENE_FRAGMENT_MOVIES = """
    id
    title
    code
    date
    rating100
    organized
    stash_ids { endpoint stash_id }
    files {
        id
        path
        basename
        width
        height
        duration
        video_codec
        audio_codec
        bit_rate
        frame_rate
        fingerprints { type value }
    }
    studio {
        id
        name
        parent_studio {
            id
            name
            parent_studio {
                id
                name
                parent_studio {
                    id
                    name
                    parent_studio { id name }
                }
            }
        }
    }
    tags { id name }
    performers {
        id
        name
        gender
        favorite
        rating100
        stash_ids { endpoint stash_id }
    }
    movies {
        movie { name date }
        scene_index
    }
"""


# =============================================================================
# VERSION COMPARISON
# =============================================================================

# Version cutoff: ``groups`` field was introduced in Stash v0.27.0
_GROUPS_MIN_VERSION = (0, 27, 0)


def _parse_version(version_str: str) -> tuple[int, ...] | None:
    """Parse a version string into a tuple of ints.

    Handles formats like "0.27.0", "v0.30.1-81-g86abe7b2", etc.
    Returns None if parsing fails.
    """
    try:
        cleaned = version_str.strip().lstrip("v").split("-")[0]
        parts = cleaned.split(".")
        return tuple(int(p) for p in parts)
    except (ValueError, AttributeError):
        return None


def _select_fragment(stash_version: str) -> str:
    """Select the appropriate GraphQL fragment based on Stash version.

    - Version >= 0.27.0: use SCENE_FRAGMENT (with ``groups``).
    - Version < 0.27.0: use SCENE_FRAGMENT_MOVIES (with ``movies``).
    - Empty string or unparseable: default to SCENE_FRAGMENT (assume latest).
    """
    if not stash_version:
        return SCENE_FRAGMENT

    parsed = _parse_version(stash_version)
    if parsed is None:
        return SCENE_FRAGMENT

    if parsed >= _GROUPS_MIN_VERSION:
        return SCENE_FRAGMENT
    else:
        return SCENE_FRAGMENT_MOVIES


# =============================================================================
# SCENE FETCHING
# =============================================================================


def fetch_scene_ids_paginated(
    stash,
    scene_filter: dict = None,
    per_page: int = 100,
) -> tuple[int, list[int]]:
    """Fetch all scene IDs via paginated lightweight queries.

    Uses an id-only fragment sorted by ``id ASC`` for stable pagination
    even when scenes are modified during the bulk operation.

    Args:
        stash: A StashInterface instance.
        scene_filter: Optional filter dict (e.g., ``{"organized": True}``
            for backfill mode). Defaults to ``{}`` if None.
        per_page: Number of scene IDs to fetch per page.

    Returns:
        A ``(count, scene_ids)`` tuple where *count* is the total from
        the initial count query and *scene_ids* is the list of integer IDs
        collected across all pages.
    """
    f = scene_filter if scene_filter is not None else {}

    # First call: get total count without fetching data
    count_result = stash.find_scenes(
        f=f, filter={"page": 1, "per_page": 0}, fragment="id", get_count=True
    )
    # find_scenes with get_count=True returns (count, scenes) tuple
    if isinstance(count_result, tuple):
        count = count_result[0]
    else:
        count = 0

    if count == 0:
        return (0, [])

    # Paginate through all scenes collecting IDs
    all_ids: list[int] = []
    page = 1
    while True:
        scenes = stash.find_scenes(
            f=f,
            filter={
                "page": page,
                "per_page": per_page,
                "sort": "id",
                "direction": "ASC",
            },
            fragment="id",
        )
        if not scenes:
            break
        for s in scenes:
            all_ids.append(int(s["id"]))
        page += 1

    return (count, all_ids)


def fetch_scene(stash, scene_id: int, stash_version: str = "") -> dict | None:
    """Fetch a scene with full metadata via a custom GraphQL fragment.

    Selects the appropriate fragment based on the Stash version to handle
    the ``groups`` vs ``movies`` field rename in v0.27.

    Args:
        stash: A StashInterface instance.
        scene_id: The numeric scene ID to fetch.
        stash_version: The Stash server version string (e.g., "0.27.0").
            Empty string or unparseable values default to the latest fragment.

    Returns:
        The scene dict with full nested data, or None if not found.
    """
    fragment = _select_fragment(stash_version)
    return stash.find_scene(scene_id, fragment=fragment)


# =============================================================================
# TAG REMOVAL
# =============================================================================


def remove_tag_from_scene(stash, scene_id: int, tag_name: str) -> bool:
    """Remove a tag from a scene by tag name.

    Looks up the tag ID by exact name match, fetches the scene's current
    tags, removes the matching tag, and updates the scene via GraphQL.

    Used by the clean_tag modifier to remove the organizing
    tag after a successful rename/move operation.

    Args:
        stash: A StashInterface instance.
        scene_id: The numeric scene ID to update.
        tag_name: The exact tag name to remove.

    Returns:
        True if the tag was removed, False if tag not found or update failed.
    """
    try:
        # 1. Find tag by exact name match
        tags = stash.find_tags(
            f={"name": {"value": tag_name, "modifier": "EQUALS"}}
        )
        if not tags:
            log.warning(
                f"Scene {scene_id}: tag '{tag_name}' not found in Stash "
                f"(clean_tag skipped)"
            )
            return False

        tag_id = tags[0]["id"]

        # 2. Fetch scene to get current tag IDs
        scene = stash.find_scene(scene_id, fragment="id tags { id }")
        if scene is None:
            log.warning(
                f"Scene {scene_id}: not found when removing tag "
                f"'{tag_name}'"
            )
            return False

        # 3. Build new tag list excluding the removed tag
        new_tag_ids = [
            int(t["id"])
            for t in scene.get("tags", [])
            if str(t["id"]) != str(tag_id)
        ]

        # 4. Update scene with new tag list
        stash.update_scene({"id": scene_id, "tag_ids": new_tag_ids})
        return True

    except Exception as e:
        log.warning(
            f"Scene {scene_id}: failed to remove tag '{tag_name}': {e}"
        )
        return False


# =============================================================================
# LIBRARY PATH QUERIES
# =============================================================================


def fetch_library_paths(stash) -> list[str]:
    """Get library root paths from Stash configuration.

    Queries the Stash GraphQL API for configured library stash paths and
    normalizes each path with ``os.path.normpath()``.

    Args:
        stash: A StashInterface instance.

    Returns:
        A list of normalized library path strings. Empty list if config
        is missing or malformed.
    """
    config = stash.get_configuration(
        fragment="general { stashes { path } }"
    )
    if config is None:
        return []

    try:
        stashes = config.get("general", {}).get("stashes", [])
    except AttributeError:
        return []

    return [os.path.normpath(s["path"]) for s in stashes if s.get("path")]


# =============================================================================
# PATH VALIDATION
# =============================================================================


def is_path_under_library(dest_path: str, library_paths: list[str]) -> bool:
    """Check if a destination path is under any configured library root.

    Pure function -- no Stash dependency. Normalizes both paths before
    comparison and checks with ``os.sep`` to avoid partial prefix matches
    (e.g., ``/media/videos2`` should NOT match ``/media/videos``).

    Args:
        dest_path: The destination file path to validate.
        library_paths: List of library root paths (may have trailing slashes).

    Returns:
        True if dest_path is under (or equal to) any library path.
    """
    dest = os.path.normpath(dest_path)
    for lib_path in library_paths:
        lib = os.path.normpath(lib_path)
        if dest == lib or dest.startswith(lib + os.sep):
            return True
    return False
