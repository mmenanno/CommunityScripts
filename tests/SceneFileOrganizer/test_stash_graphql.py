"""Tests for stash_graphql module: scene fetching, library paths, path validation, tag removal."""

from unittest.mock import MagicMock, patch

import pytest

from stash_graphql import (
    SCENE_FRAGMENT,
    SCENE_FRAGMENT_MOVIES,
    fetch_library_paths,
    fetch_scene,
    fetch_scene_ids_paginated,
    is_path_under_library,
    remove_tag_from_scene,
)


# =============================================================================
# fetch_scene — version-aware fragment selection
# =============================================================================


class TestFetchSceneFragmentSelection:
    """Tests for fetch_scene version-based fragment selection."""

    def test_fetch_scene_uses_groups_fragment_for_v027(self):
        """Version 0.27.0 should use the SCENE_FRAGMENT (with groups)."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "1", "title": "Test"}

        result = fetch_scene(stash, 1, stash_version="0.27.0")

        stash.find_scene.assert_called_once_with(1, fragment=SCENE_FRAGMENT)
        assert result == {"id": "1", "title": "Test"}

    def test_fetch_scene_uses_movies_fragment_for_v026(self):
        """Version 0.26.2 should use the SCENE_FRAGMENT_MOVIES (with movies)."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "2"}

        fetch_scene(stash, 2, stash_version="0.26.2")

        stash.find_scene.assert_called_once_with(2, fragment=SCENE_FRAGMENT_MOVIES)

    def test_fetch_scene_defaults_to_groups_on_empty_version(self):
        """Empty string version should default to SCENE_FRAGMENT (latest)."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "3"}

        fetch_scene(stash, 3, stash_version="")

        stash.find_scene.assert_called_once_with(3, fragment=SCENE_FRAGMENT)

    def test_fetch_scene_defaults_to_groups_on_invalid_version(self):
        """Non-parseable version string should fall back to SCENE_FRAGMENT."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "4"}

        fetch_scene(stash, 4, stash_version="not-a-version")

        stash.find_scene.assert_called_once_with(4, fragment=SCENE_FRAGMENT)

    def test_fetch_scene_returns_none_for_missing_scene(self):
        """When stash.find_scene returns None, fetch_scene should return None."""
        stash = MagicMock()
        stash.find_scene.return_value = None

        result = fetch_scene(stash, 999, stash_version="0.27.0")

        assert result is None

    def test_fetch_scene_uses_groups_for_version_above_027(self):
        """Version 0.28.1 (above 0.27.0) should use SCENE_FRAGMENT."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "5"}

        fetch_scene(stash, 5, stash_version="0.28.1")

        stash.find_scene.assert_called_once_with(5, fragment=SCENE_FRAGMENT)

    def test_fetch_scene_uses_movies_for_version_022(self):
        """Version 0.22.0 (well below 0.27) should use SCENE_FRAGMENT_MOVIES."""
        stash = MagicMock()
        stash.find_scene.return_value = {"id": "6"}

        fetch_scene(stash, 6, stash_version="0.22.0")

        stash.find_scene.assert_called_once_with(6, fragment=SCENE_FRAGMENT_MOVIES)


# =============================================================================
# fetch_library_paths — configuration query
# =============================================================================


class TestFetchLibraryPaths:
    """Tests for fetch_library_paths configuration extraction."""

    def test_fetch_library_paths_extracts_paths(self):
        """Should extract and normalize paths from stash config."""
        stash = MagicMock()
        stash.get_configuration.return_value = {
            "general": {
                "stashes": [
                    {"path": "/media/videos"},
                    {"path": "/media/photos/"},
                ]
            }
        }

        result = fetch_library_paths(stash)

        assert len(result) == 2
        assert "/media/videos" in result
        # Trailing slash should be normalized away
        assert "/media/photos" in result

    def test_fetch_library_paths_empty_on_missing_config(self):
        """Should return empty list when config is missing or malformed."""
        stash = MagicMock()
        stash.get_configuration.return_value = {}

        result = fetch_library_paths(stash)

        assert result == []

    def test_fetch_library_paths_empty_on_none_config(self):
        """Should return empty list when get_configuration returns None."""
        stash = MagicMock()
        stash.get_configuration.return_value = None

        result = fetch_library_paths(stash)

        assert result == []

    def test_fetch_library_paths_empty_stashes_list(self):
        """Should return empty list when stashes list is empty."""
        stash = MagicMock()
        stash.get_configuration.return_value = {
            "general": {"stashes": []}
        }

        result = fetch_library_paths(stash)

        assert result == []

    def test_fetch_library_paths_calls_correct_fragment(self):
        """Should call get_configuration with the correct GraphQL fragment."""
        stash = MagicMock()
        stash.get_configuration.return_value = {"general": {"stashes": []}}

        fetch_library_paths(stash)

        stash.get_configuration.assert_called_once()
        call_kwargs = stash.get_configuration.call_args
        # Verify the fragment mentions stashes and path
        fragment_arg = call_kwargs.kwargs.get("fragment") or call_kwargs.args[0] if call_kwargs.args else call_kwargs.kwargs.get("fragment", "")
        assert "stashes" in fragment_arg
        assert "path" in fragment_arg


# =============================================================================
# is_path_under_library — pure path validation
# =============================================================================


class TestIsPathUnderLibrary:
    """Tests for is_path_under_library path validation."""

    def test_is_path_under_library_true_for_subdirectory(self):
        """/media/videos/Studio/file.mp4 should be under /media/videos."""
        assert is_path_under_library(
            "/media/videos/Studio/file.mp4",
            ["/media/videos"],
        ) is True

    def test_is_path_under_library_false_for_sibling(self):
        """/media/music/file.mp3 should NOT be under /media/videos."""
        assert is_path_under_library(
            "/media/music/file.mp3",
            ["/media/videos"],
        ) is False

    def test_is_path_under_library_true_for_exact_match(self):
        """/media/videos should match /media/videos exactly."""
        assert is_path_under_library(
            "/media/videos",
            ["/media/videos"],
        ) is True

    def test_is_path_under_library_false_for_partial_prefix(self):
        """/media/videos2/file.mp4 should NOT be under /media/videos.

        Must check with os.sep to avoid partial prefix match.
        """
        assert is_path_under_library(
            "/media/videos2/file.mp4",
            ["/media/videos"],
        ) is False

    def test_is_path_under_library_multiple_libraries(self):
        """Should return True if path is under any of the library paths."""
        assert is_path_under_library(
            "/data/archive/scene.mp4",
            ["/media/videos", "/data/archive"],
        ) is True

    def test_is_path_under_library_empty_libraries(self):
        """Should return False when library list is empty."""
        assert is_path_under_library(
            "/media/videos/file.mp4",
            [],
        ) is False

    def test_is_path_under_library_normalizes_trailing_slash(self):
        """Should handle paths with trailing slashes via normalization."""
        assert is_path_under_library(
            "/media/videos/file.mp4",
            ["/media/videos/"],
        ) is True


# =============================================================================
# fetch_scene_ids_paginated — paginated ID fetching
# =============================================================================


class TestFetchSceneIdsPaginated:
    """Tests for fetch_scene_ids_paginated paginated scene ID fetching."""

    def test_returns_correct_count_and_ids_single_page(self):
        """Single page of results: returns correct count and IDs."""
        stash = MagicMock()
        # Count call returns (5, [])
        stash.find_scenes.side_effect = [
            (5, []),  # count call
            [{"id": "1"}, {"id": "2"}, {"id": "3"}, {"id": "4"}, {"id": "5"}],  # page 1
            [],  # page 2 (empty, stops pagination)
        ]

        count, ids = fetch_scene_ids_paginated(stash)

        assert count == 5
        assert ids == [1, 2, 3, 4, 5]

    def test_paginates_across_multiple_pages(self):
        """Multiple pages: collects IDs from all pages until empty."""
        stash = MagicMock()
        stash.find_scenes.side_effect = [
            (5, []),  # count call
            [{"id": "1"}, {"id": "2"}, {"id": "3"}],  # page 1
            [{"id": "4"}, {"id": "5"}],  # page 2
            [],  # page 3 (empty, stops pagination)
        ]

        count, ids = fetch_scene_ids_paginated(stash, per_page=3)

        assert count == 5
        assert ids == [1, 2, 3, 4, 5]

    def test_returns_empty_when_no_scenes_match(self):
        """No scenes match filter: returns (0, [])."""
        stash = MagicMock()
        stash.find_scenes.return_value = (0, [])

        count, ids = fetch_scene_ids_paginated(stash)

        assert count == 0
        assert ids == []

    def test_passes_scene_filter_to_find_scenes(self):
        """scene_filter dict is passed through to find_scenes calls."""
        stash = MagicMock()
        stash.find_scenes.side_effect = [
            (1, []),  # count call
            [{"id": "10"}],  # page 1
            [],  # page 2 (empty)
        ]

        fetch_scene_ids_paginated(stash, scene_filter={"organized": True})

        # Check the count call used the filter
        count_call = stash.find_scenes.call_args_list[0]
        assert count_call.kwargs.get("f") == {"organized": True} or \
            (count_call.args and count_call.args[0] == {"organized": True})

        # Check the data call used the filter
        data_call = stash.find_scenes.call_args_list[1]
        assert data_call.kwargs.get("f") == {"organized": True} or \
            (data_call.args and data_call.args[0] == {"organized": True})

    def test_uses_sort_by_id_asc(self):
        """Pagination filter includes sort by id ASC for stable ordering."""
        stash = MagicMock()
        stash.find_scenes.side_effect = [
            (1, []),  # count call
            [{"id": "1"}],  # page 1
            [],  # page 2 (empty)
        ]

        fetch_scene_ids_paginated(stash)

        # The data call (second call) should use sort=id, direction=ASC
        data_call = stash.find_scenes.call_args_list[1]
        filter_arg = data_call.kwargs.get("filter", {})
        assert filter_arg.get("sort") == "id"
        assert filter_arg.get("direction") == "ASC"


# =============================================================================
# remove_tag_from_scene — tag removal via GraphQL
# =============================================================================


class TestRemoveTagFromScene:
    """Tests for remove_tag_from_scene tag removal."""

    def test_remove_tag_calls_graphql_mutation(self):
        """Looks up tag by name, fetches scene tags, updates scene without removed tag."""
        stash = MagicMock()
        # find_tags returns the tag with id "99"
        stash.find_tags.return_value = [{"id": "99"}]
        # find_scene returns scene with two tags
        stash.find_scene.return_value = {
            "id": "42",
            "tags": [{"id": "99"}, {"id": "50"}],
        }
        stash.update_scene.return_value = True

        result = remove_tag_from_scene(stash, scene_id=42, tag_name="JAV")

        # Should look up tag by exact name match
        stash.find_tags.assert_called_once_with(
            f={"name": {"value": "JAV", "modifier": "EQUALS"}}
        )
        # Should update scene with tag 99 removed, only tag 50 remaining
        stash.update_scene.assert_called_once()
        update_args = stash.update_scene.call_args[0][0]
        assert update_args["id"] == 42
        assert 99 not in update_args["tag_ids"]
        assert 50 in update_args["tag_ids"]

    def test_remove_tag_not_found_logs_warning(self):
        """When tag name not found in Stash, log warning and return False."""
        stash = MagicMock()
        stash.find_tags.return_value = []

        result = remove_tag_from_scene(stash, scene_id=42, tag_name="NonExistent")

        assert result is False
        stash.update_scene.assert_not_called()

    def test_remove_tag_returns_true_on_success(self):
        """Returns True when tag is successfully removed from scene."""
        stash = MagicMock()
        stash.find_tags.return_value = [{"id": "99"}]
        stash.find_scene.return_value = {
            "id": "42",
            "tags": [{"id": "99"}, {"id": "50"}],
        }
        stash.update_scene.return_value = True

        result = remove_tag_from_scene(stash, scene_id=42, tag_name="JAV")

        assert result is True
