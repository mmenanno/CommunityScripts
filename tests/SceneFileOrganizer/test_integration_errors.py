"""Integration tests for error handling and graceful degradation.

These tests verify that process_scene() handles edge cases gracefully
without crashing: scene not found, no files, missing metadata, and
move failures. All tests use MockStash and real Config objects, calling
process_scene() directly to exercise the full pipeline.
"""

from unittest.mock import patch

import pytest

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationErrorHandling:
    """End-to-end integration tests for error handling through process_scene."""

    def test_scene_not_found_returns_false(
        self,
        mock_stash_factory,
        make_integration_config,
    ):
        """Scene ID not in MockStash returns False with no moves."""
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
        )
        # Empty scenes dict -- scene 999 does not exist
        stash = mock_stash_factory(
            scenes={},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 999, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    def test_scene_with_no_files_returns_false(
        self,
        mock_stash_factory,
        make_integration_config,
    ):
        """Scene with empty files list returns False with no moves."""
        # Build scene dict directly with empty files list
        scene = {
            "id": "50",
            "title": "No Files Scene",
            "code": None,
            "date": "2024-01-15",
            "rating100": 80,
            "organized": True,
            "stash_ids": [],
            "files": [],
            "studio": {"id": "5", "name": "TestStudio", "parent_studio": None},
            "tags": [],
            "performers": [],
            "groups": [],
        }
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
        )
        stash = mock_stash_factory(
            scenes={50: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 50, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    def test_scene_with_no_title_and_no_code_processes(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene with title=None and code=None does not crash."""
        scene = make_integration_scene(
            scene_id=51,
            title=None,
            code=None,
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
        )
        stash = mock_stash_factory(
            scenes={51: scene},
            library_paths=["/media/videos"],
        )

        # Must not raise an exception -- result can be True or False
        result = sfo.process_scene(
            stash, 51, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert isinstance(result, bool)

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_move_failure_returns_false(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Move failure (GraphQL error) returns False."""
        scene = make_integration_scene(
            scene_id=52,
            title="Move Fail Scene",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={52: scene},
            library_paths=["/media/videos"],
        )

        # Override move_files to raise an exception (simulating GraphQL error)
        def raise_error(move_input):
            raise Exception("GraphQL error")

        stash.move_files = raise_error

        result = sfo.process_scene(
            stash, 52, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
