"""Tests for the SceneFileOrganizer entry point module.

Covers version checking, mode dispatch, hook guards, session cookie forwarding,
and the process_scene() orchestrator with dry-run mode.
All tests use mocks -- no running Stash instance required.
"""

import json
import os
import sys
from unittest.mock import MagicMock, call, patch

import pytest

import scene_file_organizer as sfo
from config_loader import Config, DEFAULTS, deep_merge, TagModifiers
from exclusions import ExclusionResult


# ---------------------------------------------------------------------------
# Version check tests
# ---------------------------------------------------------------------------


class TestCheckMinimumVersion:
    """Tests for check_minimum_version()."""

    def test_check_minimum_version_pass(self):
        """Version 0.28.0 >= 0.22.0 should return True."""
        version = MagicMock()
        version.major = 0
        version.minor = 28
        version.patch = 0
        version.__str__ = MagicMock(return_value="v0.28.0")
        assert sfo.check_minimum_version(version, "0.22.0") is True

    def test_check_minimum_version_exact(self):
        """Version 0.22.0 >= 0.22.0 should return True (exact match)."""
        version = MagicMock()
        version.major = 0
        version.minor = 22
        version.patch = 0
        version.__str__ = MagicMock(return_value="v0.22.0")
        assert sfo.check_minimum_version(version, "0.22.0") is True

    def test_check_minimum_version_fail(self):
        """Version 0.20.0 < 0.22.0 should return False."""
        version = MagicMock()
        version.major = 0
        version.minor = 20
        version.patch = 0
        version.__str__ = MagicMock(return_value="v0.20.0")
        assert sfo.check_minimum_version(version, "0.22.0") is False

    def test_check_minimum_version_parse_error(self):
        """Unparseable version should return True (graceful fallback)."""

        class BadVersion:
            pass

        assert sfo.check_minimum_version(BadVersion(), "0.22.0") is True


# ---------------------------------------------------------------------------
# Mode dispatch tests
# ---------------------------------------------------------------------------


class TestModeDispatch:
    """Tests for main() mode dispatch logic."""

    @patch("scene_file_organizer.handle_hook")
    @patch("scene_file_organizer.StashInterface")
    @patch("scene_file_organizer.sys.stdin")
    def test_mode_dispatch_hook(self, mock_stdin, mock_si_class, mock_handler, mock_hook_json):
        """No mode (hook trigger) should dispatch to handle_hook."""
        mock_stdin.read.return_value = json.dumps(mock_hook_json)
        mock_stash = MagicMock()
        mock_version = MagicMock()
        mock_version.major = 0
        mock_version.minor = 28
        mock_version.patch = 0
        mock_version.__str__ = MagicMock(return_value="v0.28.0")
        mock_stash.stash_version.return_value = mock_version
        mock_si_class.return_value = mock_stash

        sfo.main()

        mock_handler.assert_called_once_with(mock_stash, mock_hook_json)


# ---------------------------------------------------------------------------
# Hook handler guard tests
# ---------------------------------------------------------------------------


class TestHookGuards:
    """Tests for handle_hook() early-exit guards."""

    @patch("scene_file_organizer.is_enabled", return_value=False)
    def test_hook_skips_when_disabled(self, mock_enabled, mock_hook_json):
        """Hook should return early when plugin is disabled."""
        mock_stash = MagicMock()

        with patch("scene_file_organizer.log") as mock_log:
            sfo.handle_hook(mock_stash, mock_hook_json)
            mock_log.info.assert_not_called()

    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_skips_when_irrelevant_field_updated(self, mock_enabled, mock_server_connection):
        """Hook should return early when only irrelevant fields are in inputFields."""
        mock_stash = MagicMock()
        json_input = {
            "server_connection": mock_server_connection,
            "args": {
                "hookContext": {
                    "id": 42,
                    "type": "Scene.Update.Post",
                    "input": {"details": "Some notes", "id": 42},
                    "inputFields": ["details", "id"],
                }
            },
        }

        with patch("scene_file_organizer.log") as mock_log:
            sfo.handle_hook(mock_stash, json_input)
            mock_log.info.assert_not_called()

    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_skips_when_organized_false(self, mock_enabled, mock_server_connection):
        """Hook should return early when organized is being set to False."""
        mock_stash = MagicMock()
        json_input = {
            "server_connection": mock_server_connection,
            "args": {
                "hookContext": {
                    "id": 42,
                    "type": "Scene.Update.Post",
                    "input": {"organized": False, "id": 42},
                    "inputFields": ["organized", "id"],
                }
            },
        }

        with patch("scene_file_organizer.log") as mock_log:
            sfo.handle_hook(mock_stash, json_input)
            mock_log.info.assert_not_called()

    @patch("scene_file_organizer.process_scene")
    @patch("scene_file_organizer.is_dry_run", return_value=True)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_processes_when_organized(
        self, mock_enabled, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_process, mock_hook_json
    ):
        """Hook should call process_scene when all guards pass and config loads."""
        mock_stash = MagicMock()
        mock_version = MagicMock()
        mock_version.major = 0
        mock_version.minor = 28
        mock_version.patch = 0
        mock_version.__str__ = MagicMock(return_value="v0.28.0")
        mock_stash.stash_version.return_value = mock_version
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config

        sfo.handle_hook(mock_stash, mock_hook_json)

        mock_process.assert_called_once_with(
            mock_stash, 42, mock_config, ["/media"], True, "v0.28.0"
        )


# ---------------------------------------------------------------------------
# Version block test
# ---------------------------------------------------------------------------


class TestVersionBlock:
    """Tests for version check blocking old Stash versions."""

    @patch("scene_file_organizer.handle_hook")
    @patch("scene_file_organizer.StashInterface")
    @patch("scene_file_organizer.sys.stdin")
    @patch("scene_file_organizer.log")
    def test_version_check_blocks_old_stash(
        self, mock_log, mock_stdin, mock_si_class, mock_hook, mock_task_json
    ):
        """Old Stash version should block execution with clear error message."""
        task_json = mock_task_json("bulk")
        mock_stdin.read.return_value = json.dumps(task_json)
        mock_stash = MagicMock()
        mock_version = MagicMock()
        mock_version.major = 0
        mock_version.minor = 20
        mock_version.patch = 0
        mock_version.__str__ = MagicMock(return_value="v0.20.0")
        mock_stash.stash_version.return_value = mock_version
        mock_si_class.return_value = mock_stash

        sfo.main()

        # Should log an error about version
        mock_log.error.assert_called_once()
        error_msg = mock_log.error.call_args[0][0]
        assert "0.22.0" in error_msg
        assert "v0.20.0" in error_msg

        # Should NOT dispatch to any handler
        mock_hook.assert_not_called()


# ---------------------------------------------------------------------------
# Server connection passthrough test
# ---------------------------------------------------------------------------


class TestServerConnectionPassthrough:
    """Tests that server_connection is passed directly to StashInterface."""

    @patch("scene_file_organizer.handle_hook")
    @patch("scene_file_organizer.StashInterface")
    @patch("scene_file_organizer.sys.stdin")
    def test_server_connection_passed_directly(
        self, mock_stdin, mock_si_class, mock_handler, mock_hook_json, mock_server_connection
    ):
        """StashInterface must be called with the complete server_connection dict."""
        mock_stdin.read.return_value = json.dumps(mock_hook_json)
        mock_stash = MagicMock()
        mock_version = MagicMock()
        mock_version.major = 0
        mock_version.minor = 28
        mock_version.patch = 0
        mock_version.__str__ = MagicMock(return_value="v0.28.0")
        mock_stash.stash_version.return_value = mock_version
        mock_si_class.return_value = mock_stash

        sfo.main()

        # Verify StashInterface was called with the COMPLETE server_connection
        mock_si_class.assert_called_once_with(mock_server_connection, force_api_key=True)


# ---------------------------------------------------------------------------
# process_scene() test helpers
# ---------------------------------------------------------------------------


def _make_mock_stash(version="0.27.0"):
    """Create a mock StashInterface with a given version."""
    mock = MagicMock()
    v = MagicMock()
    parts = [int(x) for x in version.split(".")]
    v.major = parts[0]
    v.minor = parts[1]
    v.patch = parts[2]
    v.__str__ = MagicMock(return_value=f"v{version}")
    mock.stash_version.return_value = v
    return mock


def _make_test_config(**overrides):
    """Build a Config from DEFAULTS with optional overrides.

    Overrides are section-level dicts merged into DEFAULTS:
        _make_test_config(filename={"use_default": True, "default": "$date $title"})
    """
    merged = deep_merge(DEFAULTS, overrides)
    return Config.from_dict(merged)


def _make_scene(
    scene_id=42,
    title="Test Scene",
    current_path="/media/videos/scene.mp4",
    tags=None,
    studio_name="TestStudio",
    performers=None,
):
    """Return a minimal valid scene dict with sensible defaults."""
    return {
        "id": str(scene_id),
        "title": title,
        "code": None,
        "date": "2024-01-15",
        "rating100": 80,
        "organized": True,
        "stash_ids": [],
        "files": [
            {
                "id": "100",
                "path": current_path,
                "basename": os.path.basename(current_path),
                "video_codec": "h264",
                "audio_codec": "aac",
                "width": 1920,
                "height": 1080,
                "duration": 1800.0,
                "bit_rate": 5000000,
                "frame_rate": 30.0,
                "fingerprints": [],
            }
        ],
        "studio": {"id": "5", "name": studio_name, "parent_studio": None}
        if studio_name
        else None,
        "tags": tags or [],
        "performers": performers or [],
        "groups": [],
    }


# Shared patch paths for process_scene dependencies
_PS_PATCHES = {
    "fetch_scene": "scene_file_organizer.fetch_scene",
    "check_exclusions": "scene_file_organizer.check_exclusions",
    "build_scene_output": "scene_file_organizer.build_scene_output",
    "is_path_under_library": "scene_file_organizer.is_path_under_library",
    "resolve_unique_filename": "scene_file_organizer.resolve_unique_filename",
    "move_scene_file": "scene_file_organizer.move_scene_file",
    "find_associated_files": "scene_file_organizer.find_associated_files",
    "move_associated_files": "scene_file_organizer.move_associated_files",
    "cleanup_empty_dirs": "scene_file_organizer.cleanup_empty_dirs",
}


# ---------------------------------------------------------------------------
# process_scene() tests - Happy path
# ---------------------------------------------------------------------------


class TestProcessSceneHappyPath:
    """Tests for the full process_scene pipeline on success paths."""

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new_title.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_full_pipeline(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """Full pipeline: fetch, not excluded, compute, validate, move, returns True."""
        scene = _make_scene()
        mock_fetch.return_value = scene
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title"},
        )

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is True
        mock_fetch.assert_called_once_with(stash, 42, "")
        mock_excl.assert_called_once()
        mock_build.assert_called_once_with(scene, config)
        mock_move.assert_called_once_with(stash, "100", "/media/videos/studio", "new_title.mp4")

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new_title.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_logs_moved_message(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """After successful move, log.info is called with 'Moved: old -> new'."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        sfo.process_scene(stash, 42, config, ["/media/videos"])

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        moved_msgs = [m for m in info_calls if "Moved:" in m]
        assert len(moved_msgs) == 1
        assert "/media/videos/scene.mp4" in moved_msgs[0]
        assert "/media/videos/studio/new_title.mp4" in moved_msgs[0]


# ---------------------------------------------------------------------------
# process_scene() tests - Exclusion
# ---------------------------------------------------------------------------


class TestProcessSceneExclusion:
    """Tests for exclusion skip behavior."""

    @patch(_PS_PATCHES["move_scene_file"])
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(True, "tag: DoNotRename"))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_excluded_scene(
        self, mock_log, mock_fetch, mock_excl, mock_move,
    ):
        """Excluded scene: move NOT called, returns False, logs exclusion reason."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_move.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("excluded" in m.lower() and "tag: DoNotRename" in m for m in info_calls)


# ---------------------------------------------------------------------------
# process_scene() tests - Same-path short-circuit
# ---------------------------------------------------------------------------


class TestProcessSceneSamePath:
    """Tests for same-path short-circuit."""

    @patch(_PS_PATCHES["move_scene_file"])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("scene.mp4", "/media/videos", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_same_path(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib, mock_move,
    ):
        """Same dest as current: move NOT called, log.debug, returns False."""
        mock_fetch.return_value = _make_scene(current_path="/media/videos/scene.mp4")
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_move.assert_not_called()
        mock_log.debug.assert_called()
        debug_msg = mock_log.debug.call_args[0][0]
        assert "already at target" in debug_msg.lower()


# ---------------------------------------------------------------------------
# process_scene() tests - Validation
# ---------------------------------------------------------------------------


class TestProcessSceneValidation:
    """Tests for input validation and early-exit conditions."""

    @patch(_PS_PATCHES["fetch_scene"], return_value=None)
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_missing_scene(self, mock_log, mock_fetch):
        """fetch_scene returns None: returns False."""
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 99, config, ["/media/videos"])

        assert result is False
        mock_log.warning.assert_called()
        assert "not found" in mock_log.warning.call_args[0][0].lower()

    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_no_files(self, mock_log, mock_fetch, mock_excl):
        """Scene with empty files list: returns False."""
        scene = _make_scene()
        scene["files"] = []
        mock_fetch.return_value = scene
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_log.warning.assert_called()
        assert "no files" in mock_log.warning.call_args[0][0].lower()

    @patch(_PS_PATCHES["build_scene_output"], return_value=None)
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_build_output_none(
        self, mock_log, mock_fetch, mock_excl, mock_build,
    ):
        """build_scene_output returns None: returns False."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_log.warning.assert_called()
        assert "build_scene_output" in mock_log.warning.call_args[0][0]

    @patch(_PS_PATCHES["move_scene_file"])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=False)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/external/drive", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_path_not_under_library(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib, mock_move,
    ):
        """Destination not under library: move NOT called, log.error, returns False."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_move.assert_not_called()
        mock_log.error.assert_called()
        assert "not under any library" in mock_log.error.call_args[0][0].lower()


# ---------------------------------------------------------------------------
# process_scene() tests - Duplicate handling
# ---------------------------------------------------------------------------


class TestProcessSceneDuplicate:
    """Tests for duplicate filename resolution."""

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new_title_1.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_uses_unique_filename(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """Duplicate detected: move called with suffixed name."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is True
        mock_move.assert_called_once_with(
            stash, "100", "/media/videos/studio", "new_title_1.mp4"
        )

    @patch(_PS_PATCHES["move_scene_file"])
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value=None)
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_skips_on_duplicate_exhausted(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move,
    ):
        """resolve_unique_filename returns None: move NOT called, log.error."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_move.assert_not_called()
        mock_log.error.assert_called()
        assert "duplicate retries" in mock_log.error.call_args[0][0].lower()

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_passes_max_retries_from_config(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """Verify resolve_unique_filename receives max_retries from config."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config(files={"max_duplicate_retries": 3})

        sfo.process_scene(stash, 42, config, ["/media/videos"])

        mock_resolve.assert_called_once_with(
            "/media/videos/studio", "new.mp4", 3
        )


# ---------------------------------------------------------------------------
# process_scene() tests - Move failure
# ---------------------------------------------------------------------------


class TestProcessSceneMoveFailure:
    """Tests for move failure handling."""

    @patch(_PS_PATCHES["find_associated_files"])
    @patch(_PS_PATCHES["move_scene_file"], return_value=False)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_handles_move_failure(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc,
    ):
        """move_scene_file returns False: log.error, returns False, no associated move."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is False
        mock_log.error.assert_called()
        assert "move failed" in mock_log.error.call_args[0][0].lower()
        mock_find_assoc.assert_not_called()


# ---------------------------------------------------------------------------
# process_scene() tests - Associated files
# ---------------------------------------------------------------------------


class TestProcessSceneAssociatedFiles:
    """Tests for associated file move behavior."""

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"])
    @patch(_PS_PATCHES["find_associated_files"])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_moves_associated_files(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """Associated files found: move_associated_files called with correct args."""
        mock_fetch.return_value = _make_scene()
        mock_find_assoc.return_value = [
            "/media/videos/scene.srt",
            "/media/videos/scene.funscript",
        ]
        mock_move_assoc.return_value = [
            ("/media/videos/scene.srt", "/media/videos/studio/new.srt"),
            ("/media/videos/scene.funscript", "/media/videos/studio/new.funscript"),
        ]
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(stash, 42, config, ["/media/videos"])

        assert result is True
        mock_move_assoc.assert_called_once_with(
            ["/media/videos/scene.srt", "/media/videos/scene.funscript"],
            "scene",  # old stem
            "new",    # new stem
            "/media/videos/studio",
        )

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_no_associated_files(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """No associated files: move_associated_files NOT called."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        sfo.process_scene(stash, 42, config, ["/media/videos"])

        mock_move_assoc.assert_not_called()


# ---------------------------------------------------------------------------
# process_scene() tests - Cleanup
# ---------------------------------------------------------------------------


class TestProcessSceneCleanup:
    """Tests for empty directory cleanup behavior."""

    @patch(_PS_PATCHES["cleanup_empty_dirs"])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_cleans_empty_dirs(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """After move, cleanup_empty_dirs called with source dir and library paths."""
        mock_fetch.return_value = _make_scene()
        mock_cleanup.return_value = ["/media/videos"]
        stash = _make_mock_stash()
        config = _make_test_config(paths={"remove_empty_folders": True})
        lib_paths = ["/media/videos"]

        sfo.process_scene(stash, 42, config, lib_paths)

        mock_cleanup.assert_called_once_with("/media/videos", lib_paths)

    @patch(_PS_PATCHES["cleanup_empty_dirs"])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_skips_cleanup_when_disabled(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """remove_empty_folders=False: cleanup_empty_dirs NOT called."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config(paths={"remove_empty_folders": False})

        sfo.process_scene(stash, 42, config, ["/media/videos"])

        mock_cleanup.assert_not_called()


# ---------------------------------------------------------------------------
# process_scene() tests - Dry-run mode
# ---------------------------------------------------------------------------


class TestProcessSceneDryRun:
    """Tests for dry-run mode output."""

    @patch(_PS_PATCHES["move_scene_file"])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_dry_run_logs_paths(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc, mock_move,
    ):
        """Dry-run: logs [DRY RUN], old path, new path. move NOT called."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title"},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=True
        )

        assert result is True
        mock_move.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("[DRY RUN]" in m for m in info_calls)
        assert any("Old:" in m and "/media/videos/scene.mp4" in m for m in info_calls)
        assert any("New:" in m for m in info_calls)

    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_dry_run_logs_template_info(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc,
    ):
        """Dry-run: logs template match description."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$date $title"},
        )

        sfo.process_scene(stash, 42, config, ["/media/videos"], dry_run=True)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        fn_tmpl_msgs = [m for m in info_calls if "Filename template:" in m]
        pt_tmpl_msgs = [m for m in info_calls if "Path template:" in m]
        assert len(fn_tmpl_msgs) == 1
        assert len(pt_tmpl_msgs) == 1

    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_dry_run_logs_variables(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc,
    ):
        """Dry-run: logs used variables dict."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$date $title"},
        )

        sfo.process_scene(stash, 42, config, ["/media/videos"], dry_run=True)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        var_msgs = [m for m in info_calls if "Variables:" in m]
        assert len(var_msgs) == 1
        # Should contain at least date and title references
        assert "date" in var_msgs[0] or "title" in var_msgs[0]

    @patch(_PS_PATCHES["find_associated_files"])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new_title.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_process_scene_dry_run_logs_associated_files(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc,
    ):
        """Dry-run with associated files: logs associated file renames."""
        mock_fetch.return_value = _make_scene()
        mock_find_assoc.return_value = ["/media/videos/scene.srt"]
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title"},
        )

        sfo.process_scene(stash, 42, config, ["/media/videos"], dry_run=True)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assoc_msgs = [m for m in info_calls if "Associated:" in m]
        assert len(assoc_msgs) == 1
        assert "scene.srt" in assoc_msgs[0]
        assert "new_title.srt" in assoc_msgs[0]

    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_process_scene_dry_run_returns_true(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib, mock_find_assoc,
    ):
        """Dry-run: returns True (scene was processed, just not moved)."""
        mock_fetch.return_value = _make_scene()
        stash = _make_mock_stash()
        config = _make_test_config()

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=True
        )

        assert result is True


# ---------------------------------------------------------------------------
# process_scene() tests - handle_hook integration
# ---------------------------------------------------------------------------


class TestHandleHookCallsProcessScene:
    """Tests that handle_hook correctly calls process_scene with all args."""

    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media/videos"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_handle_hook_calls_process_scene(
        self, mock_enabled, mock_load_config, mock_dry_run,
        mock_process, mock_fetch_libs, mock_hook_json,
    ):
        """handle_hook passes correct scene_id, config, library_paths, dry_run, version."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config

        sfo.handle_hook(mock_stash, mock_hook_json)

        mock_process.assert_called_once_with(
            mock_stash, 42, mock_config, ["/media/videos"], False, "v0.28.0"
        )

    @patch("scene_file_organizer.fetch_scene")
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media/videos"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_processes_metadata_change_on_organized_scene(
        self, mock_enabled, mock_load_config, mock_dry_run,
        mock_process, mock_fetch_libs, mock_fetch_scene, mock_server_connection,
    ):
        """Metadata change on organized scene triggers process_scene with scene_data."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config
        scene_data = {"id": "42", "organized": True}
        mock_fetch_scene.return_value = scene_data

        json_input = {
            "server_connection": mock_server_connection,
            "args": {
                "hookContext": {
                    "id": 42,
                    "type": "Scene.Update.Post",
                    "input": {"studio_id": "5", "id": 42},
                    "inputFields": ["studio_id", "id"],
                }
            },
        }

        sfo.handle_hook(mock_stash, json_input)

        mock_fetch_scene.assert_called_once_with(mock_stash, 42, "v0.28.0")
        mock_process.assert_called_once_with(
            mock_stash, 42, mock_config, ["/media/videos"], False,
            "v0.28.0", scene_data=scene_data,
        )

    @patch("scene_file_organizer.fetch_scene")
    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_skips_metadata_change_on_unorganized_scene(
        self, mock_enabled, mock_fetch_scene, mock_server_connection,
    ):
        """Metadata change on unorganized scene does not trigger process_scene."""
        mock_stash = _make_mock_stash("0.28.0")
        scene_data = {"id": "42", "organized": False}
        mock_fetch_scene.return_value = scene_data

        json_input = {
            "server_connection": mock_server_connection,
            "args": {
                "hookContext": {
                    "id": 42,
                    "type": "Scene.Update.Post",
                    "input": {"title": "New Title", "id": 42},
                    "inputFields": ["title", "id"],
                }
            },
        }

        with patch("scene_file_organizer.load_config") as mock_load_config, \
             patch("scene_file_organizer.is_dry_run", return_value=False), \
             patch("scene_file_organizer.fetch_library_paths", return_value=["/media"]), \
             patch("scene_file_organizer.process_scene") as mock_process:
            mock_load_config.return_value = MagicMock()
            sfo.handle_hook(mock_stash, json_input)
            mock_process.assert_not_called()

    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media/videos"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.is_enabled", return_value=True)
    def test_hook_organizing_takes_priority(
        self, mock_enabled, mock_load_config, mock_dry_run,
        mock_process, mock_fetch_libs, mock_server_connection,
    ):
        """When organized=True and a relevant field both present, Case 1 path (no pre-fetch)."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_load_config.return_value = mock_config

        json_input = {
            "server_connection": mock_server_connection,
            "args": {
                "hookContext": {
                    "id": 42,
                    "type": "Scene.Update.Post",
                    "input": {"organized": True, "studio_id": "5", "id": 42},
                    "inputFields": ["organized", "studio_id", "id"],
                }
            },
        }

        with patch("scene_file_organizer.fetch_scene") as mock_fetch_scene:
            sfo.handle_hook(mock_stash, json_input)
            # Case 1 path: no pre-fetch needed
            mock_fetch_scene.assert_not_called()
            # process_scene called without scene_data
            mock_process.assert_called_once_with(
                mock_stash, 42, mock_config, ["/media/videos"], False, "v0.28.0"
            )


# ---------------------------------------------------------------------------
# handle_bulk_rename() tests
# ---------------------------------------------------------------------------


class TestHandleBulkRename:
    """Tests for handle_bulk_rename() bulk processing."""

    def setup_method(self):
        """Store and set _plugin_dir for each test."""
        self._original_plugin_dir = sfo._plugin_dir
        sfo._plugin_dir = "/tmp/test"

    def teardown_method(self):
        """Restore _plugin_dir after each test."""
        sfo._plugin_dir = self._original_plugin_dir

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.load_config")
    def test_bulk_rename_processes_all_scenes(
        self, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """Bulk rename calls process_scene for each scene ID."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 1
        mock_load_config.return_value = mock_config

        sfo.handle_bulk_rename(mock_stash)

        assert mock_process.call_count == 3
        mock_process.assert_any_call(
            mock_stash, 1, mock_config, ["/media"], False, "v0.28.0"
        )
        mock_process.assert_any_call(
            mock_stash, 2, mock_config, ["/media"], False, "v0.28.0"
        )
        mock_process.assert_any_call(
            mock_stash, 3, mock_config, ["/media"], False, "v0.28.0"
        )

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.log")
    def test_bulk_rename_reports_progress(
        self, mock_log, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """log.progress called with incremental values and final 1.0."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config

        sfo.handle_bulk_rename(mock_stash)

        progress_calls = [c[0][0] for c in mock_log.progress.call_args_list]
        assert pytest.approx(progress_calls[0], abs=0.01) == 1 / 3
        assert pytest.approx(progress_calls[1], abs=0.01) == 2 / 3
        assert pytest.approx(progress_calls[2], abs=0.01) == 3 / 3
        # Final explicit 1.0 call
        assert progress_calls[-1] == 1.0

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.load_config")
    def test_bulk_rename_applies_delay(
        self, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """time.sleep called N-1 times (not after last scene)."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 2
        mock_load_config.return_value = mock_config

        sfo.handle_bulk_rename(mock_stash)

        assert mock_sleep.call_count == 2  # N-1 = 3-1 = 2
        mock_sleep.assert_called_with(2)

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(0, []))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene")
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.log")
    def test_bulk_rename_skips_no_scenes(
        self, mock_log, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """No scenes: process_scene NOT called, logs 'No scenes found'."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 1
        mock_load_config.return_value = mock_config

        sfo.handle_bulk_rename(mock_stash)

        mock_process.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("No scenes found" in m for m in info_calls)

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene")
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.log")
    def test_bulk_rename_counts_results(
        self, mock_log, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """Summary log contains correct moved and skipped counts."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_process.side_effect = [True, False, True]

        sfo.handle_bulk_rename(mock_stash)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "complete" in m.lower()]
        assert len(summary) == 1
        assert "2 moved" in summary[0]
        assert "1 skipped" in summary[0]

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene")
    @patch("scene_file_organizer.load_config")
    @patch("scene_file_organizer.log")
    def test_bulk_rename_handles_exception(
        self, mock_log, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """Exception in one scene: error logged, others processed, summary includes failed."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_process.side_effect = [True, Exception("DB error"), True]

        sfo.handle_bulk_rename(mock_stash)

        assert mock_process.call_count == 3
        error_calls = [c[0][0] for c in mock_log.error.call_args_list]
        assert any("unexpected error" in m.lower() for m in error_calls)
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "complete" in m.lower()]
        assert "1 failed" in summary[0]

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated", return_value=(3, [1, 2, 3]))
    @patch("scene_file_organizer.is_dry_run", return_value=False)
    @patch("scene_file_organizer.fetch_library_paths", return_value=["/media"])
    @patch("scene_file_organizer.process_scene", return_value=True)
    @patch("scene_file_organizer.load_config")
    def test_bulk_rename_skips_delay_when_zero(
        self, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """bulk_delay=0: time.sleep NOT called."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config

        sfo.handle_bulk_rename(mock_stash)

        mock_sleep.assert_not_called()

    @patch("scene_file_organizer.time.sleep")
    @patch("scene_file_organizer.fetch_scene_ids_paginated")
    @patch("scene_file_organizer.is_dry_run")
    @patch("scene_file_organizer.fetch_library_paths")
    @patch("scene_file_organizer.process_scene")
    @patch("scene_file_organizer.load_config", return_value=None)
    def test_bulk_rename_returns_when_config_none(
        self, mock_load_config, mock_process, mock_fetch_libs,
        mock_dry_run, mock_fetch_ids, mock_sleep,
    ):
        """load_config returns None: process_scene NOT called."""
        mock_stash = _make_mock_stash("0.28.0")

        sfo.handle_bulk_rename(mock_stash)

        mock_process.assert_not_called()
        mock_fetch_ids.assert_not_called()


# ---------------------------------------------------------------------------
# _normalize_path() tests
# ---------------------------------------------------------------------------


class TestNormalizePath:
    """Tests for the _normalize_path() helper."""

    def test_normalize_path_nfc(self):
        """NFD decomposed e-acute equals NFC composed e-acute after normalization."""
        nfd_path = "cafe\u0301.mp4"  # NFD: e + combining acute
        nfc_path = "caf\u00e9.mp4"   # NFC: precomposed e-acute
        assert sfo._normalize_path(nfd_path) == sfo._normalize_path(nfc_path)

    def test_normalize_path_normpath(self):
        """Double slashes are normalized to single slash."""
        result = sfo._normalize_path("/media/videos//scene.mp4")
        assert result == "/media/videos/scene.mp4"

    def test_normalize_path_plain_ascii(self):
        """Plain ASCII paths pass through unchanged."""
        path = "/media/videos/scene.mp4"
        assert sfo._normalize_path(path) == path


# ---------------------------------------------------------------------------
# handle_backfill() tests
# ---------------------------------------------------------------------------

# Patch paths used by handle_backfill tests
_BF_PATCHES = {
    "load_config": "scene_file_organizer.load_config",
    "fetch_scene_ids_paginated": "scene_file_organizer.fetch_scene_ids_paginated",
    "fetch_scene": "scene_file_organizer.fetch_scene",
    "fetch_library_paths": "scene_file_organizer.fetch_library_paths",
    "is_dry_run": "scene_file_organizer.is_dry_run",
    "check_exclusions": "scene_file_organizer.check_exclusions",
    "build_scene_output": "scene_file_organizer.build_scene_output",
    "process_scene": "scene_file_organizer.process_scene",
    "time_sleep": "scene_file_organizer.time.sleep",
    "log": "scene_file_organizer.log",
}


class TestHandleBackfill:
    """Tests for handle_backfill() backfill/audit processing."""

    def setup_method(self):
        """Store and set _plugin_dir for each test."""
        self._original_plugin_dir = sfo._plugin_dir
        sfo._plugin_dir = "/tmp/test"

    def teardown_method(self):
        """Restore _plugin_dir after each test."""
        sfo._plugin_dir = self._original_plugin_dir

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_audit_mode_logs_misplaced(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Audit mode: misplaced scene logged with [AUDIT], process_scene NOT called."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        # Scene path does NOT match expected path
        mock_fetch_scene.return_value = _make_scene(current_path="/media/videos/old.mp4")

        sfo.handle_backfill(mock_stash)

        mock_process.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        audit_msgs = [m for m in info_calls if "[AUDIT]" in m]
        assert len(audit_msgs) == 1
        assert "/media/videos/old.mp4" in audit_msgs[0]
        assert "/media/videos/studio/new.mp4" in audit_msgs[0]
        # Summary shows misplaced and would-move
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert len(summary) == 1
        assert "Misplaced:  1" in summary[0]
        assert "Would-move: 1" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=("scene.mp4", "/media/videos", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_audit_mode_matched_scene(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Audit mode: matched scene shows Matched: 1, Misplaced: 0."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        # Scene path matches expected path
        mock_fetch_scene.return_value = _make_scene(current_path="/media/videos/scene.mp4")

        sfo.handle_backfill(mock_stash)

        mock_process.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert len(summary) == 1
        assert "Matched:    1" in summary[0]
        assert "Misplaced:  0" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"], return_value=True)
    @patch(_BF_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=False)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_fix_mode_calls_process_scene(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Fix mode: misplaced scene calls process_scene with dry_run=False."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene(current_path="/media/videos/old.mp4")

        sfo.handle_backfill(mock_stash)

        mock_process.assert_called_once_with(
            mock_stash, 42, mock_config, ["/media"],
            dry_run=False, stash_version_str="v0.28.0",
            scene_data=mock_fetch_scene.return_value,
        )
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Moved:" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"], return_value=False)
    @patch(_BF_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=False)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_fix_mode_counts_failed_move(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Fix mode: process_scene returns False counts as failed, not moved."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene(current_path="/media/videos/old.mp4")

        sfo.handle_backfill(mock_stash)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Failed:     1" in summary[0]
        assert "Moved:" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"])
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(True, "tag: Skip"))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_skips_excluded_scenes(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Excluded scene: counted as excluded, build_scene_output NOT called."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene()

        sfo.handle_backfill(mock_stash)

        mock_build.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Excluded:   1" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"])
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_counts_no_files_as_failed(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """Scene with empty files list: counted as failed."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        scene = _make_scene()
        scene["files"] = []
        mock_fetch_scene.return_value = scene

        sfo.handle_backfill(mock_stash)

        mock_build.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Failed:     1" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=None)
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_counts_build_output_none_as_failed(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """build_scene_output returns None: counted as failed."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene()

        sfo.handle_backfill(mock_stash)

        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Failed:     1" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"])
    @patch(_BF_PATCHES["check_exclusions"])
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(0, []))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_no_organized_scenes(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """No organized scenes: logs message, process_scene NOT called."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config

        sfo.handle_backfill(mock_stash)

        mock_process.assert_not_called()
        mock_fetch_scene.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("No organized scenes" in m for m in info_calls)

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=("scene.mp4", "/media/videos", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_organized_filter_passed(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """fetch_scene_ids_paginated called with scene_filter={'organized': True}."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene()

        sfo.handle_backfill(mock_stash)

        mock_fetch_ids.assert_called_once_with(
            mock_stash, scene_filter={"organized": True}
        )

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=("scene.mp4", "/media/videos", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(2, [42, 43]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_reports_progress(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """2 matched scenes: log.progress called with 0.5, 1.0, and final 1.0."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        mock_fetch_scene.return_value = _make_scene()

        sfo.handle_backfill(mock_stash)

        progress_calls = [c[0][0] for c in mock_log.progress.call_args_list]
        assert pytest.approx(progress_calls[0], abs=0.01) == 0.5
        assert pytest.approx(progress_calls[1], abs=0.01) == 1.0
        # Final explicit 1.0
        assert progress_calls[-1] == 1.0

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"], return_value=("caf\u00e9.mp4", "/media/videos", None))
    @patch(_BF_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"], return_value=(1, [42]))
    @patch(_BF_PATCHES["is_dry_run"], return_value=True)
    @patch(_BF_PATCHES["fetch_library_paths"], return_value=["/media"])
    @patch(_BF_PATCHES["load_config"])
    def test_backfill_nfc_comparison_matches_nfd_nfc(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """NFD scene path matches NFC expected path after normalization: Matched: 1."""
        mock_stash = _make_mock_stash("0.28.0")
        mock_config = MagicMock()
        mock_config.general.bulk_delay = 0
        mock_load_config.return_value = mock_config
        # Scene path uses NFD decomposed form (e + combining acute)
        mock_fetch_scene.return_value = _make_scene(
            current_path="/media/videos/cafe\u0301.mp4"
        )
        # build_scene_output returns NFC form (precomposed e-acute)
        # (already set in decorator: return_value=("caf\u00e9.mp4", "/media/videos", None))

        sfo.handle_backfill(mock_stash)

        mock_process.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        summary = [m for m in info_calls if "Backfill complete" in m]
        assert "Matched:    1" in summary[0]

    @patch(_BF_PATCHES["time_sleep"])
    @patch(_BF_PATCHES["log"])
    @patch(_BF_PATCHES["process_scene"])
    @patch(_BF_PATCHES["build_scene_output"])
    @patch(_BF_PATCHES["check_exclusions"])
    @patch(_BF_PATCHES["fetch_scene"])
    @patch(_BF_PATCHES["fetch_scene_ids_paginated"])
    @patch(_BF_PATCHES["is_dry_run"])
    @patch(_BF_PATCHES["fetch_library_paths"])
    @patch(_BF_PATCHES["load_config"], return_value=None)
    def test_backfill_returns_when_config_none(
        self, mock_load_config, mock_fetch_libs, mock_dry_run,
        mock_fetch_ids, mock_fetch_scene, mock_excl, mock_build,
        mock_process, mock_log, mock_sleep,
    ):
        """load_config returns None: no further processing."""
        mock_stash = _make_mock_stash("0.28.0")

        sfo.handle_backfill(mock_stash)

        mock_fetch_ids.assert_not_called()
        mock_fetch_scene.assert_not_called()
        mock_process.assert_not_called()


# ---------------------------------------------------------------------------
# process_scene() tests - Tag modifier behaviors
# ---------------------------------------------------------------------------


class TestProcessSceneModifiers:
    """Tests for tag modifier wiring in process_scene: dry_run override, clean_tag, combinations."""

    @patch("scene_file_organizer.remove_tag_from_scene")
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/jav", "JAV"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_dry_run_override_forces_dry_run(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc, mock_remove_tag,
    ):
        """Per-tag dry_run=True overrides global dry_run=False: move NOT called, dry-run log."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "JAV"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title"}},
            tag_options={"JAV": {"dry_run": True}},
        )

        with patch(_PS_PATCHES["move_scene_file"]) as mock_move:
            result = sfo.process_scene(
                stash, 42, config, ["/media/videos"], dry_run=False
            )

        assert result is True
        mock_move.assert_not_called()
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("[DRY RUN]" in m for m in info_calls)

    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/studio", "Western"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_dry_run_override_not_applied_when_no_modifier(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc, mock_cleanup,
    ):
        """No tag_options for matched tag: move IS called normally with dry_run=False."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "Western"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title"},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=False
        )

        assert result is True
        mock_move.assert_called_once()

    @patch("scene_file_organizer.remove_tag_from_scene", return_value=True)
    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/jav", "JAV"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_clean_tag_called_after_successful_move(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc,
        mock_cleanup, mock_remove_tag,
    ):
        """clean_tag=True + successful move: remove_tag_from_scene called."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "JAV"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title"}},
            tag_options={"JAV": {"clean_tag": True}},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=False
        )

        assert result is True
        mock_remove_tag.assert_called_once_with(stash, 42, "JAV")

    @patch("scene_file_organizer.remove_tag_from_scene")
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/jav", "JAV"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_clean_tag_not_called_on_dry_run(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc, mock_remove_tag,
    ):
        """clean_tag=True + global dry_run=True: remove_tag NOT called (no actual move)."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "JAV"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title"}},
            tag_options={"JAV": {"clean_tag": True}},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=True
        )

        assert result is True
        mock_remove_tag.assert_not_called()

    @patch("scene_file_organizer.remove_tag_from_scene")
    @patch(_PS_PATCHES["move_scene_file"], return_value=False)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/jav", "JAV"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_clean_tag_not_called_when_move_fails(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_remove_tag,
    ):
        """clean_tag=True but move fails: remove_tag NOT called."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "JAV"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title"}},
            tag_options={"JAV": {"clean_tag": True}},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=False
        )

        assert result is False
        mock_remove_tag.assert_not_called()

    @patch("scene_file_organizer.remove_tag_from_scene")
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/jav", "JAV"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    @patch("scene_file_organizer.log")
    def test_multiple_modifiers_combined(
        self, mock_log, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_find_assoc, mock_remove_tag,
    ):
        """clean_tag=True + dry_run=True: dry_run prevents move, so clean_tag doesn't fire."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "JAV"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title"}},
            tag_options={"JAV": {"clean_tag": True, "dry_run": True}},
        )

        with patch(_PS_PATCHES["move_scene_file"]) as mock_move:
            result = sfo.process_scene(
                stash, 42, config, ["/media/videos"], dry_run=False
            )

        assert result is True
        mock_move.assert_not_called()  # dry_run override prevents move
        mock_remove_tag.assert_not_called()  # no move = no clean_tag
        info_calls = [c[0][0] for c in mock_log.info.call_args_list]
        assert any("[DRY RUN]" in m for m in info_calls)

    @patch("scene_file_organizer.remove_tag_from_scene")
    @patch(_PS_PATCHES["cleanup_empty_dirs"], return_value=[])
    @patch(_PS_PATCHES["move_associated_files"], return_value=[])
    @patch(_PS_PATCHES["find_associated_files"], return_value=[])
    @patch(_PS_PATCHES["move_scene_file"], return_value=True)
    @patch(_PS_PATCHES["resolve_unique_filename"], return_value="new.mp4")
    @patch(_PS_PATCHES["is_path_under_library"], return_value=True)
    @patch(_PS_PATCHES["build_scene_output"], return_value=("new.mp4", "/media/videos/western", "Western"))
    @patch(_PS_PATCHES["check_exclusions"], return_value=ExclusionResult(False))
    @patch(_PS_PATCHES["fetch_scene"])
    def test_modifier_on_different_tag_not_applied(
        self, mock_fetch, mock_excl, mock_build, mock_under_lib,
        mock_resolve, mock_move, mock_find_assoc, mock_move_assoc,
        mock_cleanup, mock_remove_tag,
    ):
        """TMOD isolation: modifier on JAV not applied when scene matches Western."""
        mock_fetch.return_value = _make_scene(
            tags=[{"id": "10", "name": "Western"}],
        )
        stash = _make_mock_stash()
        config = _make_test_config(
            filename={"use_default": True, "default": "$title",
                       "tag_templates": {"JAV": "$title", "Western": "$date $title"}},
            tag_options={"JAV": {"clean_tag": True}},
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"], dry_run=False
        )

        assert result is True
        mock_move.assert_called_once()
        mock_remove_tag.assert_not_called()  # clean_tag is on JAV, not Western
