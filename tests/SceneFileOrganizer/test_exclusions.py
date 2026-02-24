"""Tests for exclusions module: exclusion filtering with OR logic."""

import pytest

from config_loader import ExclusionConfig
from exclusions import ExclusionResult, check_exclusions


# =============================================================================
# Helpers
# =============================================================================


def _make_scene(
    tags=None,
    studio=None,
    files=None,
):
    """Build a minimal scene dict for exclusion testing."""
    scene = {}
    if tags is not None:
        scene["tags"] = tags
    if studio is not None:
        scene["studio"] = studio
    if files is not None:
        scene["files"] = files
    return scene


# =============================================================================
# Tag exclusion
# =============================================================================


class TestExcludedByTag:
    """Tests for tag-based exclusion checking."""

    def test_excluded_by_tag_case_insensitive(self):
        """Scene with tag 'DoNotRename' should be excluded by ['donotrename']."""
        scene = _make_scene(
            tags=[{"name": "DoNotRename"}],
            studio={"name": "Some Studio"},
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(tags=["donotrename"])

        result = check_exclusions(scene, config)

        assert result.excluded is True
        assert "tag:" in result.reason
        assert "DoNotRename" in result.reason  # Original case preserved

    def test_scene_with_no_tags_skips_tag_check(self):
        """Scene with no tags key should not error, moves to next check."""
        scene = _make_scene(
            studio={"name": "Some Studio"},
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(tags=["donotrename"])

        result = check_exclusions(scene, config)

        assert result.excluded is False

    def test_tag_no_match(self):
        """Scene tags that don't match exclusion list should not be excluded."""
        scene = _make_scene(
            tags=[{"name": "Favorite"}, {"name": "HD"}],
            studio={"name": "Some Studio"},
        )
        config = ExclusionConfig(tags=["donotrename", "skip"])

        result = check_exclusions(scene, config)

        assert result.excluded is False


# =============================================================================
# Studio exclusion
# =============================================================================


class TestExcludedByStudio:
    """Tests for studio-based exclusion checking."""

    def test_excluded_by_studio_case_insensitive(self):
        """Scene with studio 'Evil Angel' should be excluded by ['evil angel']."""
        scene = _make_scene(
            tags=[],
            studio={"name": "Evil Angel"},
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(studios=["evil angel"])

        result = check_exclusions(scene, config)

        assert result.excluded is True
        assert "studio:" in result.reason
        assert "Evil Angel" in result.reason

    def test_scene_with_no_studio_skips_studio_check(self):
        """Scene with no studio key should not error, moves to next check."""
        scene = _make_scene(
            tags=[],
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(studios=["evil angel"])

        result = check_exclusions(scene, config)

        assert result.excluded is False

    def test_scene_with_null_studio_skips_studio_check(self):
        """Scene with studio=None should not error."""
        scene = _make_scene(
            tags=[],
            studio=None,
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(studios=["evil angel"])

        result = check_exclusions(scene, config)

        assert result.excluded is False


# =============================================================================
# Path exclusion
# =============================================================================


class TestExcludedByPath:
    """Tests for path-based exclusion checking."""

    def test_excluded_by_path_regex(self):
        """Scene with path matching regex pattern should be excluded."""
        scene = _make_scene(
            tags=[],
            studio={"name": "Good Studio"},
            files=[{"path": "/mnt/archive/old/file.mp4"}],
        )
        config = ExclusionConfig(paths=[r"/archive/"])

        result = check_exclusions(scene, config)

        assert result.excluded is True
        assert "path:" in result.reason
        assert "/archive/" in result.reason

    def test_excluded_by_path_exact(self):
        """Scene with path matching exact regex should be excluded."""
        scene = _make_scene(
            tags=[],
            studio={"name": "Good Studio"},
            files=[{"path": "/tmp/test.mp4"}],
        )
        config = ExclusionConfig(paths=[r"^/tmp/test\.mp4$"])

        result = check_exclusions(scene, config)

        assert result.excluded is True

    def test_scene_with_no_files_skips_path_check(self):
        """Scene with empty files list should not error, returns not excluded."""
        scene = _make_scene(
            tags=[],
            studio={"name": "Good Studio"},
            files=[],
        )
        config = ExclusionConfig(paths=[r"/archive/"])

        result = check_exclusions(scene, config)

        assert result.excluded is False


# =============================================================================
# Combined / edge cases
# =============================================================================


class TestExclusionCombined:
    """Tests for combined exclusion behavior and edge cases."""

    def test_not_excluded_when_no_rules_match(self):
        """Scene that matches no exclusion rules returns excluded=False."""
        scene = _make_scene(
            tags=[{"name": "Favorite"}],
            studio={"name": "Good Studio"},
            files=[{"path": "/media/videos/scene.mp4"}],
        )
        config = ExclusionConfig(
            tags=["donotrename"],
            studios=["evil angel"],
            paths=[r"/archive/"],
        )

        result = check_exclusions(scene, config)

        assert result.excluded is False
        assert result.reason == ""

    def test_not_excluded_when_all_exclusion_lists_empty(self):
        """Empty tags/studios/paths lists should return not excluded."""
        scene = _make_scene(
            tags=[{"name": "Favorite"}],
            studio={"name": "Good Studio"},
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(tags=[], studios=[], paths=[])

        result = check_exclusions(scene, config)

        assert result.excluded is False

    def test_first_match_wins_tag_over_studio(self):
        """When scene matches both tag and studio, reason should mention tag (checked first)."""
        scene = _make_scene(
            tags=[{"name": "DoNotRename"}],
            studio={"name": "Evil Angel"},
            files=[{"path": "/media/scene.mp4"}],
        )
        config = ExclusionConfig(
            tags=["donotrename"],
            studios=["evil angel"],
        )

        result = check_exclusions(scene, config)

        assert result.excluded is True
        assert "tag:" in result.reason
        assert "DoNotRename" in result.reason

    def test_exclusion_result_dataclass(self):
        """ExclusionResult should have correct defaults."""
        result = ExclusionResult(excluded=False)
        assert result.excluded is False
        assert result.reason == ""

        result_with_reason = ExclusionResult(excluded=True, reason="tag: test")
        assert result_with_reason.excluded is True
        assert result_with_reason.reason == "tag: test"

    def test_empty_scene_dict(self):
        """Completely empty scene dict should not error."""
        scene = {}
        config = ExclusionConfig(
            tags=["skip"],
            studios=["bad studio"],
            paths=[r"/archive/"],
        )

        result = check_exclusions(scene, config)

        assert result.excluded is False
