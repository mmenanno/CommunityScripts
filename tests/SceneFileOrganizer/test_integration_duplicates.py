"""Integration tests for duplicate filename detection end-to-end.

These tests verify that duplicate filename handling (suffix appending, retry
exhaustion) works correctly when composed with the full metadata extraction,
template resolution, and file operation pipeline.

Each test calls ``sfo.process_scene()`` with a real Config object and a
MockStash, exercising the complete pipeline. Duplicate detection behavior is
controlled by patching ``file_operations.os.path.exists`` to simulate existing
files on disk. Only filesystem I/O is patched.
"""

import os
from unittest.mock import patch

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationDuplicates:
    """End-to-end integration tests for duplicate filename detection."""

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    def test_duplicate_filename_gets_suffix(
        self,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """When target filename already exists on disk, a _1 suffix is appended.

        Simulates a collision: Scene B resolves to the same filename as
        Scene A (already moved). The ``resolve_unique_filename`` function
        detects the collision and appends ``_1`` to Scene B's filename.
        """
        scene_b = make_integration_scene(
            scene_id=70,
            title="Same Title",
            studio_name="StudioX",
            current_path="/media/videos/b.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={70: scene_b},
            library_paths=["/media/videos"],
        )

        # Simulate: "Same Title.mp4" already exists (from Scene A),
        # but "Same Title_1.mp4" does not exist yet.
        def exists_side_effect(path):
            return path.endswith("Same Title.mp4")

        with patch(_PATCH_FO_EXISTS, side_effect=exists_side_effect):
            result = sfo.process_scene(
                stash, 70, config, ["/media/videos"],
                dry_run=False, stash_version_str="0.28.0",
            )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "Same Title_1.mp4"
        assert move["destination_folder"] == "/media/videos/StudioX"

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_no_duplicate_filename_no_suffix(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """When target filename does not exist on disk, no suffix is added.

        The original filename is used as-is when there is no collision.
        """
        scene = make_integration_scene(
            scene_id=71,
            title="Unique Title",
            studio_name="StudioX",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={71: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 71, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "Unique Title.mp4"
        assert move["destination_folder"] == "/media/videos/StudioX"

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=True)  # ALL paths "exist" on disk
    def test_duplicate_exhausts_retries_skips(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """When all suffix candidates are exhausted, the scene is skipped.

        With max_duplicate_retries=2 and os.path.exists always returning True,
        resolve_unique_filename tries "Title.mp4", "Title_1.mp4", "Title_2.mp4"
        -- all exist -- and returns None. process_scene then returns False.
        """
        scene = make_integration_scene(
            scene_id=72,
            title="Crowded Title",
            studio_name="StudioX",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            files={"max_duplicate_retries": 2},
        )
        stash = mock_stash_factory(
            scenes={72: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 72, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []
