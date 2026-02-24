"""Tests for the file_operations module.

Covers resolve_unique_filename, move_scene_file, find_associated_files,
move_associated_files, and cleanup_empty_dirs with filesystem mocking
and real temp directory structures.
"""

import os
from unittest.mock import MagicMock

import pytest

from file_operations import (
    cleanup_empty_dirs,
    find_associated_files,
    move_associated_files,
    move_scene_file,
    resolve_unique_filename,
)


# ---------------------------------------------------------------------------
# resolve_unique_filename tests
# ---------------------------------------------------------------------------


class TestResolveUniqueFilename:
    """Tests for resolve_unique_filename() function."""

    def test_unique_returns_original_when_no_conflict(self, tmp_path):
        """When no file with that name exists, return original filename."""
        result = resolve_unique_filename(str(tmp_path), "scene.mp4")
        assert result == "scene.mp4"

    def test_unique_appends_suffix_when_conflict(self, tmp_path):
        """When file exists, return stem_1.ext."""
        (tmp_path / "scene.mp4").touch()
        result = resolve_unique_filename(str(tmp_path), "scene.mp4")
        assert result == "scene_1.mp4"

    def test_unique_increments_suffix_until_free(self, tmp_path):
        """When stem.ext, stem_1.ext, stem_2.ext exist, return stem_3.ext."""
        (tmp_path / "scene.mp4").touch()
        (tmp_path / "scene_1.mp4").touch()
        (tmp_path / "scene_2.mp4").touch()
        result = resolve_unique_filename(str(tmp_path), "scene.mp4")
        assert result == "scene_3.mp4"

    def test_unique_returns_none_when_max_exceeded(self, tmp_path):
        """When max_retries=2 and stem.ext, stem_1.ext, stem_2.ext exist, return None."""
        (tmp_path / "scene.mp4").touch()
        (tmp_path / "scene_1.mp4").touch()
        (tmp_path / "scene_2.mp4").touch()
        result = resolve_unique_filename(str(tmp_path), "scene.mp4", max_retries=2)
        assert result is None

    def test_unique_unlimited_when_max_zero(self, tmp_path):
        """When max_retries=0 (unlimited), keeps trying past 99."""
        # Create files from scene.mp4 through scene_100.mp4
        (tmp_path / "scene.mp4").touch()
        for i in range(1, 101):
            (tmp_path / f"scene_{i}.mp4").touch()
        result = resolve_unique_filename(str(tmp_path), "scene.mp4", max_retries=0)
        assert result == "scene_101.mp4"


# ---------------------------------------------------------------------------
# move_scene_file tests
# ---------------------------------------------------------------------------


class TestMoveSceneFile:
    """Tests for move_scene_file() function."""

    def test_move_calls_stash_with_correct_input(self):
        """Verify move_files is called with the exact dict structure."""
        mock_stash = MagicMock()
        move_scene_file(mock_stash, "42", "/dest/folder", "new_name.mp4")
        mock_stash.move_files.assert_called_once_with({
            "ids": ["42"],
            "destination_folder": "/dest/folder",
            "destination_basename": "new_name.mp4",
        })

    def test_move_returns_true_on_success(self):
        """When stash.move_files returns normally, return True."""
        mock_stash = MagicMock()
        result = move_scene_file(mock_stash, "42", "/dest/folder", "new_name.mp4")
        assert result is True

    def test_move_returns_false_on_exception(self):
        """When stash.move_files raises Exception, return False."""
        mock_stash = MagicMock()
        mock_stash.move_files.side_effect = Exception("GraphQL error")
        result = move_scene_file(mock_stash, "42", "/dest/folder", "new_name.mp4")
        assert result is False


# ---------------------------------------------------------------------------
# find_associated_files tests
# ---------------------------------------------------------------------------


class TestFindAssociatedFiles:
    """Tests for find_associated_files() function."""

    def test_finds_direct_match_srt(self, tmp_path):
        """File scene.srt exists alongside scene.mp4. Found."""
        video = tmp_path / "scene.mp4"
        video.touch()
        srt = tmp_path / "scene.srt"
        srt.touch()
        result = find_associated_files(str(video), ["srt"])
        assert str(srt) in result

    def test_finds_suffixed_match_en_srt(self, tmp_path):
        """File scene.en.srt exists alongside scene.mp4. Found."""
        video = tmp_path / "scene.mp4"
        video.touch()
        en_srt = tmp_path / "scene.en.srt"
        en_srt.touch()
        result = find_associated_files(str(video), ["srt"])
        assert str(en_srt) in result

    def test_finds_funscript(self, tmp_path):
        """File scene.funscript exists alongside scene.mp4. Found."""
        video = tmp_path / "scene.mp4"
        video.touch()
        funscript = tmp_path / "scene.funscript"
        funscript.touch()
        result = find_associated_files(str(video), ["funscript"])
        assert str(funscript) in result

    def test_does_not_include_video_file(self, tmp_path):
        """The video file itself is not in results."""
        video = tmp_path / "scene.mp4"
        video.touch()
        srt = tmp_path / "scene.srt"
        srt.touch()
        result = find_associated_files(str(video), ["srt", "mp4"])
        assert str(video) not in result

    def test_returns_empty_for_no_matches(self, tmp_path):
        """No associated files exist. Returns []."""
        video = tmp_path / "scene.mp4"
        video.touch()
        result = find_associated_files(str(video), ["srt", "vtt", "funscript"])
        assert result == []

    def test_handles_special_chars_in_stem(self, tmp_path):
        """Filename with brackets/parens. Glob escaping works correctly."""
        video = tmp_path / "scene [2024] (1080p).mp4"
        video.touch()
        srt = tmp_path / "scene [2024] (1080p).srt"
        srt.touch()
        result = find_associated_files(str(video), ["srt"])
        assert str(srt) in result

    def test_finds_multiple_extensions(self, tmp_path):
        """Multiple associated file types found in a single call."""
        video = tmp_path / "scene.mp4"
        video.touch()
        srt = tmp_path / "scene.srt"
        srt.touch()
        vtt = tmp_path / "scene.vtt"
        vtt.touch()
        funscript = tmp_path / "scene.funscript"
        funscript.touch()
        result = find_associated_files(str(video), ["srt", "vtt", "funscript"])
        assert len(result) == 3
        assert str(srt) in result
        assert str(vtt) in result
        assert str(funscript) in result

    def test_results_are_sorted(self, tmp_path):
        """Return sorted list of absolute paths."""
        video = tmp_path / "scene.mp4"
        video.touch()
        (tmp_path / "scene.vtt").touch()
        (tmp_path / "scene.srt").touch()
        (tmp_path / "scene.funscript").touch()
        result = find_associated_files(str(video), ["srt", "vtt", "funscript"])
        assert result == sorted(result)

    def test_deduplicates_results(self, tmp_path):
        """Glob + direct match may overlap; results should be deduplicated."""
        video = tmp_path / "scene.mp4"
        video.touch()
        srt = tmp_path / "scene.srt"
        srt.touch()
        # Both glob pattern scene.*.srt and direct scene.srt could match scene.srt
        # The function should deduplicate
        result = find_associated_files(str(video), ["srt"])
        assert result.count(str(srt)) == 1


# ---------------------------------------------------------------------------
# move_associated_files tests
# ---------------------------------------------------------------------------


class TestMoveAssociatedFiles:
    """Tests for move_associated_files() function."""

    def test_moves_file_with_stem_replacement(self, tmp_path):
        """scene.en.srt becomes new_name.en.srt in dest_dir."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        srt = src_dir / "scene.en.srt"
        srt.write_text("subtitle content")

        move_associated_files(
            [str(srt)], "scene", "new_name", str(dest_dir)
        )

        assert not srt.exists()
        assert (dest_dir / "new_name.en.srt").exists()
        assert (dest_dir / "new_name.en.srt").read_text() == "subtitle content"

    def test_returns_old_new_path_tuples(self, tmp_path):
        """Verify returned list contains correct (old, new) tuples."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()
        srt = src_dir / "scene.srt"
        srt.touch()
        vtt = src_dir / "scene.vtt"
        vtt.touch()

        result = move_associated_files(
            [str(srt), str(vtt)], "scene", "renamed", str(dest_dir)
        )

        assert len(result) == 2
        old_paths = [t[0] for t in result]
        new_paths = [t[1] for t in result]
        assert str(srt) in old_paths
        assert str(vtt) in old_paths
        assert str(dest_dir / "renamed.srt") in new_paths
        assert str(dest_dir / "renamed.vtt") in new_paths

    def test_continues_on_individual_error(self, tmp_path):
        """If os.rename fails for one file, others still moved."""
        src_dir = tmp_path / "src"
        src_dir.mkdir()
        dest_dir = tmp_path / "dest"
        dest_dir.mkdir()

        good_file = src_dir / "scene.srt"
        good_file.touch()
        # A non-existent file will cause os.rename to fail
        bad_file = src_dir / "scene.vtt"
        # Deliberately do NOT create bad_file so os.rename fails

        result = move_associated_files(
            [str(bad_file), str(good_file)], "scene", "renamed", str(dest_dir)
        )

        # Good file should still be moved
        assert (dest_dir / "renamed.srt").exists()
        # Result should contain only the successfully moved file
        assert len(result) == 1
        assert result[0][0] == str(good_file)


# ---------------------------------------------------------------------------
# cleanup_empty_dirs tests
# ---------------------------------------------------------------------------


class TestCleanupEmptyDirs:
    """Tests for cleanup_empty_dirs() function."""

    def test_removes_single_empty_dir(self, tmp_path):
        """Create empty dir, verify removed and returned."""
        lib_root = tmp_path / "library"
        lib_root.mkdir()
        empty_dir = lib_root / "subdir"
        empty_dir.mkdir()

        result = cleanup_empty_dirs(str(empty_dir), [str(lib_root)])
        assert str(empty_dir) in result
        assert not empty_dir.exists()

    def test_removes_chain_of_empty_dirs(self, tmp_path):
        """Nested empty dirs. Removes all up to library root."""
        lib_root = tmp_path / "library"
        lib_root.mkdir()
        level1 = lib_root / "a"
        level1.mkdir()
        level2 = level1 / "b"
        level2.mkdir()
        level3 = level2 / "c"
        level3.mkdir()

        result = cleanup_empty_dirs(str(level3), [str(lib_root)])
        assert len(result) == 3
        assert not level3.exists()
        assert not level2.exists()
        assert not level1.exists()
        assert lib_root.exists()

    def test_stops_at_library_root(self, tmp_path):
        """Library root is empty. Does NOT remove it."""
        lib_root = tmp_path / "library"
        lib_root.mkdir()

        result = cleanup_empty_dirs(str(lib_root), [str(lib_root)])
        assert result == []
        assert lib_root.exists()

    def test_stops_at_non_empty_dir(self, tmp_path):
        """Dir has a file in it. Stops."""
        lib_root = tmp_path / "library"
        lib_root.mkdir()
        parent = lib_root / "parent"
        parent.mkdir()
        (parent / "keep_me.txt").touch()
        child = parent / "empty_child"
        child.mkdir()

        result = cleanup_empty_dirs(str(child), [str(lib_root)])
        assert len(result) == 1
        assert str(child) in result
        assert not child.exists()
        assert parent.exists()

    def test_returns_empty_for_non_empty_start(self, tmp_path):
        """Start dir has files. Returns []."""
        lib_root = tmp_path / "library"
        lib_root.mkdir()
        start = lib_root / "notempty"
        start.mkdir()
        (start / "file.txt").touch()

        result = cleanup_empty_dirs(str(start), [str(lib_root)])
        assert result == []
        assert start.exists()

    def test_handles_multiple_library_paths(self, tmp_path):
        """Stops at the correct library root when multiple are configured."""
        lib1 = tmp_path / "lib1"
        lib1.mkdir()
        lib2 = tmp_path / "lib2"
        lib2.mkdir()
        empty = lib2 / "sub"
        empty.mkdir()

        result = cleanup_empty_dirs(str(empty), [str(lib1), str(lib2)])
        assert len(result) == 1
        assert not empty.exists()
        assert lib2.exists()
