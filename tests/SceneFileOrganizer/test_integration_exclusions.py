"""Integration tests for exclusion filtering end-to-end.

These tests verify that exclusion rules (tags, studios, paths) work correctly
when composed with the full metadata extraction, template resolution, and file
operation pipeline -- not just in unit isolation.

Each test calls ``sfo.process_scene()`` with a real Config object and a
MockStash, exercising the complete pipeline from scene data through exclusion
checking, template resolution, text processing, and (where applicable) file
move operations. Only filesystem I/O is patched.
"""

from unittest.mock import patch

import scene_file_organizer as sfo

# Patch targets for filesystem I/O within file_operations module
_PATCH_FO_EXISTS = "file_operations.os.path.exists"
_PATCH_FO_ISDIR = "file_operations.os.path.isdir"
_PATCH_FO_LISTDIR = "file_operations.os.listdir"
_PATCH_FO_GLOB = "file_operations.glob.glob"


class TestIntegrationExclusions:
    """End-to-end integration tests for exclusion filtering."""

    def test_exclusion_by_tag_skips_scene(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene with an excluded tag is skipped; case-insensitive matching."""
        scene = make_integration_scene(
            scene_id=60,
            title="Excluded By Tag",
            tags=[{"id": "99", "name": "donotrename"}],  # lowercase variant
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={"tags": ["DoNotRename"]},  # mixed case in config
        )
        stash = mock_stash_factory(
            scenes={60: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 60, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    def test_exclusion_by_studio_skips_scene(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene with an excluded studio is skipped before file operations."""
        scene = make_integration_scene(
            scene_id=61,
            title="Excluded By Studio",
            studio_name="PrivateStudio",
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={"studios": ["PrivateStudio"]},
        )
        stash = mock_stash_factory(
            scenes={61: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 61, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    def test_exclusion_by_path_pattern_skips_scene(
        self,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene with a path matching an exclusion regex is skipped."""
        scene = make_integration_scene(
            scene_id=62,
            title="Excluded By Path",
            current_path="/media/videos/temp/somefile.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={"paths": ["/temp/"]},
        )
        stash = mock_stash_factory(
            scenes={62: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 62, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is False
        assert stash.moves == []

    @patch(_PATCH_FO_GLOB, return_value=[])
    @patch(_PATCH_FO_LISTDIR, return_value=["not-empty"])
    @patch(_PATCH_FO_ISDIR, return_value=False)
    @patch(_PATCH_FO_EXISTS, return_value=False)
    def test_non_excluded_scene_processes_normally(
        self,
        mock_exists,
        mock_isdir,
        mock_listdir,
        mock_glob,
        mock_stash_factory,
        make_integration_scene,
        make_integration_config,
    ):
        """Scene that does NOT match exclusion rules is processed normally.

        Confirms exclusion filters don't over-match: a scene with tags/studio
        that are close-but-not-matching the exclusion list should still be
        renamed and moved.
        """
        scene = make_integration_scene(
            scene_id=63,
            title="Not Excluded",
            studio_name="PublicStudio",
            tags=[{"id": "10", "name": "SomeTag"}],
            current_path="/media/videos/original.mp4",
        )
        config = make_integration_config(
            filename={"use_default": True, "default": "$title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
            exclusions={
                "tags": ["DoNotRename"],
                "studios": ["PrivateStudio"],
                "paths": ["/temp/"],
            },
        )
        stash = mock_stash_factory(
            scenes={63: scene},
            library_paths=["/media/videos"],
        )

        result = sfo.process_scene(
            stash, 63, config, ["/media/videos"],
            dry_run=False, stash_version_str="0.28.0",
        )

        assert result is True
        assert len(stash.moves) == 1
        move = stash.moves[0]
        assert move["destination_basename"] == "Not Excluded.mp4"
        assert move["destination_folder"] == "/media/videos/PublicStudio"
