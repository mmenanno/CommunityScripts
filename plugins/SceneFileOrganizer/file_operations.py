"""File operations for SceneFileOrganizer.

Provides MoveFiles wrapper, filesystem-based duplicate detection, associated
file discovery and move, and empty directory cleanup. Video files are moved
via Stash's GraphQL MoveFiles mutation (DB-consistent), while associated files
(subtitles, funscripts) are moved via os.rename (Stash does not track them).
"""

import glob
import os
from typing import List, Optional, Tuple

try:
    import stashapi.log as log
except ImportError:
    import logging as _logging

    log = _logging.getLogger("stashapi.log")


# =============================================================================
# DUPLICATE DETECTION
# =============================================================================


def resolve_unique_filename(
    dest_dir: str, filename: str, max_retries: int = 99
) -> Optional[str]:
    """Find a unique filename in dest_dir, appending _1, _2, etc. if needed.

    Pure function using os.path.exists() to check for collisions.

    Args:
        dest_dir: Destination directory path.
        filename: Desired filename (with extension).
        max_retries: Maximum suffix attempts. 0 = unlimited (up to 9999).

    Returns:
        A unique filename string, or None if max_retries exceeded and cap > 0.
    """
    if not os.path.exists(os.path.join(dest_dir, filename)):
        return filename

    stem, ext = os.path.splitext(filename)
    limit = max_retries if max_retries > 0 else 9999

    for i in range(1, limit + 1):
        candidate = f"{stem}_{i}{ext}"
        if not os.path.exists(os.path.join(dest_dir, candidate)):
            return candidate

    # Only return None when there is a cap (max_retries > 0)
    return None


# =============================================================================
# MOVE SCENE FILE (via Stash GraphQL)
# =============================================================================


def move_scene_file(
    stash, file_id: str, dest_folder: str, dest_basename: str
) -> bool:
    """Move a scene file via Stash's GraphQL MoveFiles mutation.

    Args:
        stash: StashInterface instance.
        file_id: The Stash file ID to move.
        dest_folder: Destination directory path.
        dest_basename: Destination filename (with extension).

    Returns:
        True on success, False on any exception.
    """
    try:
        stash.move_files(
            {
                "ids": [file_id],
                "destination_folder": dest_folder,
                "destination_basename": dest_basename,
            }
        )
        return True
    except Exception:
        return False


# =============================================================================
# ASSOCIATED FILE DISCOVERY
# =============================================================================


def find_associated_files(video_path: str, extensions: List[str]) -> List[str]:
    """Find associated files matching the video's basename stem.

    Discovers files like subtitles (.srt, .vtt) and funscripts that share
    the same stem as the video file, including suffixed variants (e.g.,
    scene.en.srt for scene.mp4).

    Args:
        video_path: Absolute path to the video file.
        extensions: List of file extensions to search for (without dots).

    Returns:
        Sorted list of absolute paths to associated files. Does NOT include
        the video file itself. Deduplicated.
    """
    video_dir = os.path.dirname(video_path)
    video_stem = os.path.splitext(os.path.basename(video_path))[0]
    escaped_stem = glob.escape(video_stem)
    associated: set = set()

    for ext in extensions:
        # Suffixed matches: stem.*.ext (e.g., scene.en.srt)
        pattern = os.path.join(video_dir, f"{escaped_stem}.*.{ext}")
        associated.update(glob.glob(pattern))

        # Direct match: stem.ext (e.g., scene.srt)
        # Use unescaped stem for os.path.exists (real filesystem path)
        exact = os.path.join(video_dir, f"{video_stem}.{ext}")
        if os.path.exists(exact):
            associated.add(exact)

    # Remove the video file itself (in case its extension was in the list)
    associated.discard(video_path)

    return sorted(associated)


# =============================================================================
# MOVE ASSOCIATED FILES
# =============================================================================


def move_associated_files(
    associated: List[str],
    old_stem: str,
    new_stem: str,
    dest_dir: str,
) -> List[Tuple[str, str]]:
    """Move associated files, replacing old stem with new stem in basename.

    Uses os.rename (not Stash MoveFiles) because Stash does not track
    associated files like subtitles and funscripts.

    Args:
        associated: List of absolute paths to associated files.
        old_stem: Original video stem to replace.
        new_stem: New video stem to use.
        dest_dir: Destination directory for moved files.

    Returns:
        List of (old_path, new_path) tuples for successfully moved files.
    """
    moved: List[Tuple[str, str]] = []

    for src_path in associated:
        src_name = os.path.basename(src_path)
        new_name = src_name.replace(old_stem, new_stem, 1)
        dest_path = os.path.join(dest_dir, new_name)
        try:
            os.rename(src_path, dest_path)
            moved.append((src_path, dest_path))
        except OSError as e:
            log.warning(f"Failed to move associated file {src_path}: {e}")

    return moved


# =============================================================================
# EMPTY DIRECTORY CLEANUP
# =============================================================================


def cleanup_empty_dirs(
    start_dir: str, library_paths: List[str]
) -> List[str]:
    """Remove empty directories walking up from start_dir to library root.

    Stops when encountering a non-empty directory, a library root path,
    a non-directory path, or an OS error.

    Args:
        start_dir: Directory to start cleanup from (typically the old source dir).
        library_paths: List of Stash library root paths (never removed).

    Returns:
        List of removed directory paths.
    """
    removed: List[str] = []
    current = os.path.normpath(start_dir)
    lib_normed = {os.path.normpath(p) for p in library_paths}

    while current and current not in lib_normed:
        if not os.path.isdir(current):
            break
        if os.listdir(current):
            break  # Non-empty directory
        try:
            os.rmdir(current)
            removed.append(current)
        except OSError:
            break  # Permission error or race condition
        current = os.path.dirname(current)

    return removed
