"""Integration tests for backfill/audit mode end-to-end pipeline.

These tests call handle_backfill() with MockStash containing organized scenes
and real Config objects. Only filesystem operations and time.sleep are patched.

Tests verify both audit-only (dry_run=True) and fix (dry_run=False) modes,
including misplaced scene detection, matched scene no-op, exclusion counting,
organized-only filtering, and summary statistics accuracy.
"""

from unittest.mock import patch, MagicMock

import pytest

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationBackfillMode:
    """End-to-end integration tests for backfill/audit mode."""

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
    def test_backfill_audit_detects_misplaced_scene(
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
        """Audit-only mode detects misplaced scene and reports without moving."""
        scene = make_integration_scene(
            scene_id=42,
            title="Misplaced",
            organized=True,
            studio_name="CorrectStudio",
            current_path="/media/videos/wrong_folder/old.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={42: scene},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # Audit-only mode: no moves
        assert stash.moves == []

        # Check [AUDIT] log message
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        audit_calls = [c for c in info_calls if "[AUDIT]" in c]
        assert len(audit_calls) >= 1
        audit_text = audit_calls[0]
        assert "wrong_folder" in audit_text or "old.mp4" in audit_text

        # Check summary stats
        summary = [c for c in info_calls if "Misplaced:" in c]
        assert len(summary) >= 1
        summary_text = summary[0]
        assert "Misplaced:  1" in summary_text or "Misplaced: 1" in summary_text
        assert "Would-move: 1" in summary_text or "Would-move:  1" in summary_text

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    def test_backfill_audit_matched_scene_no_action(
        self,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene already at correct path is counted as matched, no move."""
        # Config produces: /media/videos/StudioX/Correct.mp4
        scene = make_integration_scene(
            scene_id=43,
            title="Correct",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/StudioX/Correct.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={43: scene},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        assert stash.moves == []

        # Check summary: Matched: 1, Misplaced: 0
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Matched:" in c]
        assert len(summary) >= 1
        summary_text = summary[0]
        assert "Matched:    1" in summary_text or "Matched: 1" in summary_text
        assert "Misplaced:  0" in summary_text or "Misplaced: 0" in summary_text

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_backfill_fix_moves_misplaced_scene(
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
        """Fix mode detects misplaced scene and moves it to correct path."""
        scene = make_integration_scene(
            scene_id=44,
            title="Fix Me",
            organized=True,
            studio_name="RightStudio",
            current_path="/media/videos/wrong/old.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={44: scene},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # Fix mode: scene should be moved
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_folder"] == "/media/videos/RightStudio"
        assert move["destination_basename"] == "Fix Me.mp4"

        # Check summary reports Moved (fix mode label) in backfill summary
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Backfill complete" in c]
        assert len(summary) == 1
        assert "Moved:" in summary[0]

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_backfill_mixed_matched_and_misplaced(
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
        """Multiple scenes: some matched, some misplaced. Audit mode."""
        # Matched: already at correct path
        scene_matched_a = make_integration_scene(
            scene_id=50,
            title="MatchedA",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/StudioX/MatchedA.mp4",
        )
        # Misplaced: at wrong path
        scene_misplaced = make_integration_scene(
            scene_id=51,
            title="Misplaced",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/wrong/Misplaced.mp4",
        )
        # Matched: already at correct path
        scene_matched_b = make_integration_scene(
            scene_id=52,
            title="MatchedB",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/StudioX/MatchedB.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={50: scene_matched_a, 51: scene_misplaced, 52: scene_matched_b},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # Audit mode: no moves
        assert stash.moves == []

        # Check summary: Matched: 2, Misplaced: 1
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Matched:" in c]
        assert len(summary) >= 1
        summary_text = summary[0]
        assert "Matched:    2" in summary_text or "Matched: 2" in summary_text
        assert "Misplaced:  1" in summary_text or "Misplaced: 1" in summary_text

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    def test_backfill_only_queries_organized_scenes(
        self,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Unorganized scenes are ignored -- only organized scenes are processed."""
        scene_organized = make_integration_scene(
            scene_id=60,
            title="Organized",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/StudioX/Organized.mp4",
        )
        scene_unorganized = make_integration_scene(
            scene_id=61,
            title="Unorganized",
            organized=False,
            studio_name="StudioX",
            current_path="/media/videos/wrong/Unorganized.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={60: scene_organized, 61: scene_unorganized},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # Check summary shows Total: 1 (only the organized scene)
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Total:" in c]
        assert len(summary) >= 1
        summary_text = summary[0]
        assert "Total:      1" in summary_text or "Total: 1" in summary_text

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    def test_backfill_fix_mode_skips_already_correct(
        self,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Fix mode with a matched scene: no move needed."""
        scene = make_integration_scene(
            scene_id=70,
            title="AlreadyCorrect",
            organized=True,
            studio_name="StudioX",
            current_path="/media/videos/StudioX/AlreadyCorrect.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={70: scene},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": False},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # Scene already correct: no move
        assert stash.moves == []

        # Check summary: Matched: 1, Moved: 0
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Backfill complete" in c]
        assert len(summary) == 1
        assert "Matched:" in summary[0]
        assert "Moved:" in summary[0]

    @patch("scene_file_organizer.log")
    @patch("scene_file_organizer.time.sleep")
    def test_backfill_excluded_scene_counted(
        self,
        mock_sleep,
        mock_log,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Excluded scene is counted as excluded in summary stats."""
        scene = make_integration_scene(
            scene_id=80,
            title="SkipScene",
            organized=True,
            studio_name="StudioX",
            tags=[{"id": "99", "name": "SkipMe"}],
            current_path="/media/videos/StudioX/SkipScene.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={"tags": ["SkipMe"]},
            general={"bulk_delay": 0},
        )
        stash = mock_stash_factory(
            scenes={80: scene},
            library_paths=["/media/videos"],
            plugin_config={"enabled": True, "dry_run": True},
        )

        with patch("scene_file_organizer.load_config", return_value=config):
            sfo.handle_backfill(stash)

        # No moves
        assert stash.moves == []

        # Check summary: Excluded: 1
        info_calls = [str(c) for c in mock_log.info.call_args_list]
        summary = [c for c in info_calls if "Excluded:" in c]
        assert len(summary) >= 1
        summary_text = summary[0]
        assert "Excluded:   1" in summary_text or "Excluded: 1" in summary_text
