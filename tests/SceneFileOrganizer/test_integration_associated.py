"""Integration tests for associated file moves alongside video files.

These tests verify that associated files (subtitles, funscripts) are
correctly discovered and moved when process_scene() renames a video file.
Associated files are moved via os.rename (not Stash MoveFiles) since
Stash does not track them.

Tests patch filesystem I/O in file_operations: os.path.exists, os.path.isdir,
os.listdir, glob.glob, and os.rename.
"""

import os
from unittest.mock import MagicMock, patch, call

import pytest

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"
_PATCH_FO_RENAME = "file_operations.os.rename"


class TestIntegrationAssociatedFiles:
    """End-to-end integration tests for associated file moves through process_scene."""

    @patch(_PATCH_FO_RENAME)
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    def test_associated_srt_moves_with_video(
        self,
        mock_isdir,
        mock_listdir,
        mock_rename,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Single .srt file is discovered and moved alongside the video."""
        scene = make_integration_scene(
            scene_id=60,
            title="Great Scene",
            date="2024-03-15",
            studio_name="MyStudio",
            current_path="/media/videos/old_name.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={60: scene},
            library_paths=["/media/videos"],
        )

        # Paths that exist: the exact-match srt file for find_associated_files.
        # Paths that must NOT exist: duplicate-check paths in resolve_unique_filename.
        existing_paths = {"/media/videos/old_name.srt"}

        def exists_side_effect(path):
            return path in existing_paths

        def glob_side_effect(pattern):
            # Suffixed pattern: old_name.*.srt -> no suffixed variants
            # Other patterns -> empty
            return []

        with patch(_PATCH_FO_EXISTS, side_effect=exists_side_effect), \
             patch(_PATCH_FO_GLOB, side_effect=glob_side_effect):
            result = sfo.process_scene(
                stash, 60, config, ["/media/videos"],
                dry_run=False, stash_version_str="0.28.0",
            )

        assert result is True
        # Video moved via Stash GraphQL
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_folder"] == "/media/videos/MyStudio"
        assert move["destination_basename"] == "2024-03-15 Great Scene.mp4"

        # Associated srt moved via os.rename
        assert mock_rename.call_count == 1
        rename_call = mock_rename.call_args
        assert rename_call[0][0] == "/media/videos/old_name.srt"
        assert rename_call[0][1] == os.path.join(
            "/media/videos/MyStudio", "2024-03-15 Great Scene.srt"
        )

    @patch(_PATCH_FO_RENAME)
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    def test_multiple_associated_files_all_move(
        self,
        mock_isdir,
        mock_listdir,
        mock_rename,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Multiple associated files (.srt, .en.srt, .funscript) all move."""
        scene = make_integration_scene(
            scene_id=61,
            title="Multi Assoc Scene",
            date="2024-03-15",
            studio_name="MyStudio",
            current_path="/media/videos/old_name.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={61: scene},
            library_paths=["/media/videos"],
        )

        # Exact-match paths that exist (direct srt and funscript)
        existing_paths = {
            "/media/videos/old_name.srt",
            "/media/videos/old_name.funscript",
        }

        def exists_side_effect(path):
            return path in existing_paths

        def glob_side_effect(pattern):
            # Suffixed srt pattern: old_name.*.srt -> old_name.en.srt
            if pattern.endswith(".*.srt"):
                return ["/media/videos/old_name.en.srt"]
            # Suffixed funscript pattern: old_name.*.funscript -> none
            # All other patterns -> empty
            return []

        with patch(_PATCH_FO_EXISTS, side_effect=exists_side_effect), \
             patch(_PATCH_FO_GLOB, side_effect=glob_side_effect):
            result = sfo.process_scene(
                stash, 61, config, ["/media/videos"],
                dry_run=False, stash_version_str="0.28.0",
            )

        assert result is True
        assert len(stash.moves) == 1

        # Associated files: old_name.srt, old_name.en.srt, old_name.funscript
        # find_associated_files returns sorted list, so order is deterministic
        assert mock_rename.call_count == 3

        new_stem = "2024-03-15 Multi Assoc Scene"
        dest_dir = "/media/videos/MyStudio"

        # Collect actual rename calls as (old, new) tuples
        rename_calls = [(c[0][0], c[0][1]) for c in mock_rename.call_args_list]

        # Verify each associated file was moved with correct stem replacement
        expected = [
            (
                "/media/videos/old_name.en.srt",
                os.path.join(dest_dir, f"{new_stem}.en.srt"),
            ),
            (
                "/media/videos/old_name.funscript",
                os.path.join(dest_dir, f"{new_stem}.funscript"),
            ),
            (
                "/media/videos/old_name.srt",
                os.path.join(dest_dir, f"{new_stem}.srt"),
            ),
        ]
        assert sorted(rename_calls) == sorted(expected)

    @patch(_PATCH_FO_RENAME)
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_no_associated_files_no_extra_moves(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_rename,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene with no associated files triggers no os.rename calls."""
        scene = make_integration_scene(
            scene_id=62,
            title="Solo Scene",
            date="2024-03-15",
            studio_name="MyStudio",
            current_path="/media/videos/old_name.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={62: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 62, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        # Video moved via Stash GraphQL
        assert len(stash.moves) == 1
        # No associated files -> os.rename not called
        assert mock_rename.call_count == 0
