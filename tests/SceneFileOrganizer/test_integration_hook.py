"""Integration tests for hook mode end-to-end pipeline.

These tests use real Config objects, real build_scene_output, real metadata
extraction, and MockStash -- only filesystem operations (os.path.exists,
os.rename, os.rmdir, os.listdir, glob.glob) are patched.

Tests verify the complete pipeline from scene data through template resolution,
text processing, exclusion checks, and file move operations.
"""

import os
from unittest.mock import patch

import pytest

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationHookMode:
    """End-to-end integration tests for hook mode pipeline."""

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_default_template_renames_scene(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Default filename/path template produces correct rename target."""
        scene = make_integration_scene(
            scene_id=42,
            title="Great Scene",
            date="2024-03-15",
            studio_name="MyStudio",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={42: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 42, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_folder"] == "/media/videos/MyStudio"
        assert move["destination_basename"] == "2024-03-15 Great Scene.mp4"

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_tag_template_overrides_default(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Tag-based template takes priority over default template."""
        scene = make_integration_scene(
            scene_id=43,
            title="JAV Scene",
            code="ABC-123",
            tags=[{"id": "10", "name": "JAV"}],
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={
                "use_default": True,
                "default": "$date $title",
                "tag_templates": {"JAV": "$studio_code"},
            },
            path={
                "use_default": True,
                "default": "/media/videos/$studio",
                "tag_templates": {"JAV": "/media/videos/JAV"},
            },
        )
        stash = mock_stash_factory(
            scenes={43: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 43, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "ABC-123.mp4"
        assert move["destination_folder"] == "/media/videos/JAV"

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_with_performer_in_path(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Performer variable is expanded in path template.

        Uses a single performer with a comma-separated 'Last, First' name.
        The single_performer_in_path default (True) splits on ', ' and takes
        the first token, so the path folder uses the last name only. This is
        correct pipeline behavior -- the integration test verifies it end-to-end.
        """
        scene = make_integration_scene(
            scene_id=44,
            title="Perf Scene",
            studio_name="StudioX",
            performers=[{
                "id": "1",
                "name": "Doe, Jane",
                "gender": "FEMALE",
                "favorite": False,
                "rating100": 80,
                "stash_ids": [],
            }],
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$performer"},
        )
        stash = mock_stash_factory(
            scenes={44: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 44, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        # single_performer_in_path splits "Doe, Jane" on ", " -> takes "Doe"
        assert move["destination_folder"] == "/media/videos/Doe"
        assert move["destination_basename"] == "Perf Scene.mp4"

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_dry_run_records_no_move(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Dry-run mode logs the move but does not execute it."""
        scene = make_integration_scene(
            scene_id=45,
            title="Dry Run Scene",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={45: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 45, config, ["/media/videos"],
            dry_run=True, stash_version_str="0.28.0",
        )

        assert result is True
        assert stash.moves == []

    def test_hook_same_path_skips(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene already at target path is skipped (no move)."""
        # The template "$title" with path "/media/videos" would produce
        # "/media/videos/Already There.mp4". Set current_path to match.
        scene = make_integration_scene(
            scene_id=46,
            title="Already There",
            studio_name=None,
            current_path="/media/videos/Already There.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
        )
        stash = mock_stash_factory(
            scenes={46: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 46, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_with_studio_template(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Studio-based template overrides default template."""
        scene = make_integration_scene(
            scene_id=47,
            title="Studio Scene",
            studio_name="Deeper",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={
                "use_default": True,
                "default": "$title",
                "studio_templates": {"Deeper": "[$studio] $title"},
            },
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
        stash = mock_stash_factory(
            scenes={47: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 47, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "[Deeper] Studio Scene.mp4"
        assert move["destination_folder"] == "/media/videos/Deeper"

    def test_hook_exclusion_skips_scene(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Excluded scene (by tag) is not processed."""
        scene = make_integration_scene(
            scene_id=48,
            title="Excluded",
            tags=[{"id": "99", "name": "DoNotRename"}],
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos"},
            exclusions={"tags": ["DoNotRename"]},
        )
        stash = mock_stash_factory(
            scenes={48: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 48, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_hook_text_processing_applied(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Text processing transforms (titlecase) are applied to output.

        Path uses ^* (current directory substitution) so that titlecase
        affects the filename but the path stays under a known library root.
        Titlecase transforms path segments too (e.g., /media -> /Media),
        so library_paths must match the titlecased result.
        """
        scene = make_integration_scene(
            scene_id=49,
            title="messy title here",
            current_path="/Media/Videos/original.mp4",
        )
        config = make_integration_config(
            text={"titlecase": True},
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/Media/Videos"},
        )
        stash = mock_stash_factory(
            scenes={49: scene},
            library_paths=["/Media/Videos"],
        )

        result = sfo.process_scene(
            stash, 49, config, ["/Media/Videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "Messy Title Here.mp4"
