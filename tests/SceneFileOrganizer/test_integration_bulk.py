"""Integration tests for bulk rename mode end-to-end pipeline.

These tests call handle_bulk_rename() with MockStash containing multiple scenes
and real Config objects. Only filesystem operations and time.sleep are patched.

Tests verify the complete pipeline from paginated scene fetch through template
resolution, text processing, and file move operations for all scenes in the
MockStash scene store.
"""

from unittest.mock import patch, MagicMock

import pytest

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationBulkMode:
    """End-to-end integration tests for bulk rename mode."""

    def setup_method(self):
        """Store and set _plugin_dir for each test."""
        self._original_plugin_dir = sfo._plugin_dir
        sfo._plugin_dir = "/tmp/test"

    def teardown_method(self):
        """Restore _plugin_dir after each test."""
        sfo._plugin_dir = self._original_plugin_dir

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_bulk_processes_multiple_scenes(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Three scenes with default template all get processed and moved."""
        scene_a = make_integration_scene(
            scene_id=1,
            title="Scene Alpha",
            date="2024-01-15",
            studio_name="StudioX",
            current_path="/media/videos/a.mp4",
        )
        scene_b = make_integration_scene(
            scene_id=2,
            title="Scene Beta",
            date="2024-01-15",
            studio_name="StudioX",
            current_path="/media/videos/b.mp4",
        )
        scene_c = make_integration_scene(
            scene_id=3,
            title="Scene Gamma",
            date="2024-01-15",
            studio_name="StudioX",
            current_path="/media/videos/c.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={1: scene_a, 2: scene_b, 3: scene_c},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        assert len(stash.moves) == 3
        # Verify each move has correct destination
        basenames = sorted(m["destination_basename"] for m in stash.moves)
        assert basenames == [
            "2024-01-15 Scene Alpha.mp4",
            "2024-01-15 Scene Beta.mp4",
            "2024-01-15 Scene Gamma.mp4",
        ]
        for move in stash.moves:
            assert move["destination_folder"] == "/media/videos/StudioX"

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_bulk_with_mixed_templates(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scenes matching different templates get correct basenames."""
        scene_jav = make_integration_scene(
            scene_id=1,
            title="JAV Scene",
            code="ABC-123",
            studio_name="StudioX",
            tags=[{"id": "10", "name": "JAV"}],
            current_path="/media/videos/jav.mp4",
        )
        scene_default = make_integration_scene(
            scene_id=2,
            title="Normal Scene",
            date="2024-03-20",
            studio_name="StudioX",
            current_path="/media/videos/normal.mp4",
        )
        config = make_integration_config(
            filename={
                "use_default": True,
                "default": "$date $title",
                "tag_templates": {"JAV": "$studio_code"},
            },
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={1: scene_jav, 2: scene_default},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        assert len(stash.moves) == 2
        moves_by_basename = {m["destination_basename"]: m for m in stash.moves}
        # JAV scene uses tag template ($studio_code -> "ABC-123")
        assert "ABC-123.mp4" in moves_by_basename
        # Default scene uses default template ($date $title)
        assert "2024-03-20 Normal Scene.mp4" in moves_by_basename

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_bulk_dry_run_processes_without_moving(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Bulk in dry-run mode logs moves but does not execute them."""
        scene_a = make_integration_scene(
            scene_id=1,
            title="Dry Scene A",
            current_path="/media/videos/a.mp4",
        )
        scene_b = make_integration_scene(
            scene_id=2,
            title="Dry Scene B",
            current_path="/media/videos/b.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={1: scene_a, 2: scene_b},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        # Dry-run mode: no actual moves recorded
        assert stash.moves == []

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_bulk_skips_excluded_scenes(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Excluded scenes are counted but not moved."""
        scene_a = make_integration_scene(
            scene_id=1,
            title="Normal A",
            studio_name="StudioX",
            current_path="/media/videos/a.mp4",
        )
        scene_b = make_integration_scene(
            scene_id=2,
            title="Excluded Scene",
            studio_name="StudioX",
            tags=[{"id": "99", "name": "DoNotRename"}],
            current_path="/media/videos/b.mp4",
        )
        scene_c = make_integration_scene(
            scene_id=3,
            title="Normal C",
            studio_name="StudioX",
            current_path="/media/videos/c.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={"tags": ["DoNotRename"]},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={1: scene_a, 2: scene_b, 3: scene_c},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        # Only 2 non-excluded scenes should be moved
        assert len(stash.moves) == 2
        basenames = sorted(m["destination_basename"] for m in stash.moves)
        assert basenames == ["Normal A.mp4", "Normal C.mp4"]

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    def test_bulk_handles_no_scenes(
        self,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_config,
    ):
        """Empty library: no scenes to process, no errors."""
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        assert stash.moves == []
        # No errors should have been raised
        mock_log.error.assert_not_called()

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_bulk_reports_summary_stats(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Summary log contains correct processed/moved/skipped counts.

        3 scenes: 2 moved successfully, 1 already at target (same-path skip).
        """
        scene_moved_a = make_integration_scene(
            scene_id=1,
            title="Move Me A",
            studio_name="StudioX",
            current_path="/media/videos/old_a.mp4",
        )
        scene_moved_b = make_integration_scene(
            scene_id=2,
            title="Move Me B",
            studio_name="StudioX",
            current_path="/media/videos/old_b.mp4",
        )
        # Scene already at the correct path (same-path skip)
        scene_skip = make_integration_scene(
            scene_id=3,
            title="Already There",
            studio_name=None,
            current_path="/media/videos/Already There.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={1: scene_moved_a, 2: scene_moved_b, 3: scene_skip},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_bulk_rename(stash)

        # Check summary log output
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "complete" in c.lower()]
        assert len(summary) >= 1
        summary_text = summary[-1]
        assert "3 processed" in summary_text
        assert "2 moved" in summary_text
        assert "1 skipped" in summary_text
