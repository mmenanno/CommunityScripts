"""Tests for the path_builder module.

Covers _apply_field_transforms (field_whitespace_separator and field_replacer),
build_filename (template rendering, text processing, extension preservation,
empty-filename fallback), build_path (path construction with studio hierarchy
expansion, ^* substitution, consecutive folder deduplication, and performer-in-path
overrides), _reduce_path_length (iterative field reduction), and build_scene_output
(top-level pipeline orchestrator).
"""

import copy
import os

import pytest
from dataclasses import replace

from config_loader import (
    Config,
    FilenameConfig,
    PathConfig,
    PathManagementConfig,
    TextConfig,
)


# =============================================================================
# _apply_field_transforms tests
# =============================================================================


class TestApplyFieldTransforms:
    """Tests for _apply_field_transforms() - field-level variable transforms."""

    def test_field_whitespace_separator_replaces_spaces(self, make_text_config):
        """Variables with spaces have spaces replaced by separator."""
        from path_builder import _apply_field_transforms

        config = make_text_config(field_whitespace_separator="_")
        variables = {"title": "Scene Title", "studio": "Big Studio"}
        result = _apply_field_transforms(variables, config)
        assert result["title"] == "Scene_Title"
        assert result["studio"] == "Big_Studio"

    def test_field_whitespace_separator_empty_is_noop(self, make_text_config):
        """Empty string separator leaves values unchanged (default behavior)."""
        from path_builder import _apply_field_transforms

        config = make_text_config(field_whitespace_separator="")
        variables = {"title": "Scene Title", "studio": "Big Studio"}
        result = _apply_field_transforms(variables, config)
        assert result["title"] == "Scene Title"
        assert result["studio"] == "Big Studio"

    def test_field_whitespace_separator_skips_current_path_keys(self, make_text_config):
        """Keys current_path, current_filename, current_directory are NOT transformed."""
        from path_builder import _apply_field_transforms

        config = make_text_config(field_whitespace_separator="_")
        variables = {
            "title": "Scene Title",
            "current_path": "/media/my videos/scene.mp4",
            "current_filename": "my scene.mp4",
            "current_directory": "/media/my videos",
        }
        result = _apply_field_transforms(variables, config)
        assert result["title"] == "Scene_Title"
        assert result["current_path"] == "/media/my videos/scene.mp4"
        assert result["current_filename"] == "my scene.mp4"
        assert result["current_directory"] == "/media/my videos"

    def test_field_replacer_replaces_chars_in_specific_field(self, make_text_config):
        """field_replacer removes apostrophes from studio value only."""
        from path_builder import _apply_field_transforms

        config = make_text_config(
            field_replacer={"$studio": {"replace": "'", "with": ""}}
        )
        variables = {"studio": "Brazzers' Network", "title": "Don't Stop"}
        result = _apply_field_transforms(variables, config)
        assert result["studio"] == "Brazzers Network"
        assert result["title"] == "Don't Stop"  # title unaffected

    def test_field_replacer_strips_dollar_prefix(self, make_text_config):
        """Field names with $ prefix are matched after stripping the $."""
        from path_builder import _apply_field_transforms

        config = make_text_config(
            field_replacer={"$title": {"replace": "-", "with": " "}}
        )
        variables = {"title": "Scene-Title-Here"}
        result = _apply_field_transforms(variables, config)
        assert result["title"] == "Scene Title Here"

    def test_field_replacer_empty_dict_is_noop(self, make_text_config):
        """Empty field_replacer config leaves all values unchanged."""
        from path_builder import _apply_field_transforms

        config = make_text_config(field_replacer={})
        variables = {"title": "Some Title", "studio": "Studio's Name"}
        result = _apply_field_transforms(variables, config)
        assert result["title"] == "Some Title"
        assert result["studio"] == "Studio's Name"

    def test_field_replacer_only_affects_targeted_field(self, make_text_config):
        """Other fields are not modified when one field has a replacer."""
        from path_builder import _apply_field_transforms

        config = make_text_config(
            field_replacer={"$studio": {"replace": " ", "with": "_"}}
        )
        variables = {"studio": "Big Studio", "title": "Scene Title", "performer": "Jane Doe"}
        result = _apply_field_transforms(variables, config)
        assert result["studio"] == "Big_Studio"
        assert result["title"] == "Scene Title"
        assert result["performer"] == "Jane Doe"

    def test_does_not_mutate_input(self, make_text_config):
        """The input variables dict is not mutated."""
        from path_builder import _apply_field_transforms

        config = make_text_config(field_whitespace_separator="_")
        variables = {"title": "Scene Title"}
        original_title = variables["title"]
        _apply_field_transforms(variables, config)
        assert variables["title"] == original_title


# =============================================================================
# build_filename tests
# =============================================================================


class TestBuildFilename:
    """Tests for build_filename() - filename construction with extension preservation."""

    def _make_config(self, **text_overrides):
        """Helper to create a Config with TextConfig overrides."""
        text_config = replace(TextConfig(), **text_overrides) if text_overrides else TextConfig()
        return replace(Config(), text=text_config)

    def test_basic_rendering(self):
        """Template with variables renders and produces filename with extension."""
        from path_builder import build_filename

        config = self._make_config()
        variables = {"date": "2024-01-15", "title": "Scene"}
        result = build_filename("$date $title", variables, config, "old.mp4")
        assert result.endswith(".mp4")
        assert "2024-01-15" in result
        assert "Scene" in result

    def test_extension_preserved_verbatim(self):
        """Original extension .mp4 is reattached exactly, not titlecased."""
        from path_builder import build_filename

        config = self._make_config(titlecase=True)
        variables = {"title": "hello world"}
        result = build_filename("$title", variables, config, "scene.mp4")
        assert result.endswith(".mp4")
        # Extension must NOT become .Mp4
        assert not result.endswith(".Mp4")

    def test_extension_separated_before_processing(self):
        """Extension is NOT passed through process_text.

        Verify by using a config that removes '.' characters -- the extension
        must still have its dot intact.
        """
        from path_builder import build_filename

        config = self._make_config(remove_chars=".,#")
        variables = {"title": "Scene Title"}
        result = build_filename("$title", variables, config, "old.mp4")
        assert result.endswith(".mp4")

    def test_empty_result_falls_back_to_original_stem(self):
        """When all template variables are empty, fallback to original filename stem."""
        from path_builder import build_filename

        config = self._make_config()
        variables = {"date": "", "title": ""}
        result = build_filename("$date $title", variables, config, "original.mp4")
        assert result == "original.mp4"

    def test_whitespace_only_result_falls_back(self):
        """A result that is only whitespace after processing also triggers fallback."""
        from path_builder import build_filename

        config = self._make_config()
        variables = {"title": "   "}
        result = build_filename("$title", variables, config, "original.mp4")
        assert result == "original.mp4"

    def test_no_extension_file(self):
        """Original filename with no extension works correctly."""
        from path_builder import build_filename

        config = self._make_config()
        variables = {"title": "New Name"}
        result = build_filename("$title", variables, config, "scene_file")
        assert "New" in result or "new" in result.lower()
        # No extension means result should not have a dot-extension
        assert not result.endswith(".mp4")

    def test_dotfile_handled(self):
        """Original filename starting with dot uses os.path.splitext correctly."""
        from path_builder import build_filename

        config = self._make_config()
        variables = {"title": ""}
        # os.path.splitext(".hidden") returns (".hidden", "")
        # So the stem is ".hidden" and ext is ""
        result = build_filename("$title", variables, config, ".hidden")
        # Empty title should fallback to stem ".hidden"
        # Note: sanitize_filename strips leading dots, so the stem may be modified
        assert result  # Should not be empty

    def test_text_processing_applied(self):
        """When config has titlecase enabled, the rendered text is titlecased."""
        from path_builder import build_filename

        config = self._make_config(titlecase=True)
        variables = {"title": "hello world"}
        result = build_filename("$title", variables, config, "scene.mp4")
        # process_text with titlecase=True should titlecase "hello world" -> "Hello World"
        assert result == "Hello World.mp4"

    def test_field_transforms_applied_before_rendering(self):
        """When field_whitespace_separator is set, variable values have spaces replaced
        before template rendering (verify by checking output contains separator).

        NOTE: build_filename receives already-transformed variables. This test
        verifies the full pipeline by pre-applying _apply_field_transforms.
        """
        from path_builder import build_filename, _apply_field_transforms

        text_config = replace(TextConfig(), field_whitespace_separator="_")
        config = replace(Config(), text=text_config)
        variables = {"title": "Scene Title"}
        transformed = _apply_field_transforms(variables, text_config)
        result = build_filename("$title", transformed, config, "old.mp4")
        # The separator "_" should appear in the output
        assert "_" in result


# =============================================================================
# _expand_studio_hierarchy tests
# =============================================================================


class TestExpandStudioHierarchy:
    """Tests for _expand_studio_hierarchy() - hierarchy string to path segments."""

    def test_splits_and_sanitizes_segments(self):
        """'MindGeek/Brazzers/Deeper' produces 3 segments joined by os.sep, each sanitized."""
        from path_builder import _expand_studio_hierarchy

        result = _expand_studio_hierarchy("MindGeek/Brazzers/Deeper", " ")
        segments = result.split(os.sep)
        assert len(segments) == 3
        assert segments[0] == "MindGeek"
        assert segments[1] == "Brazzers"
        assert segments[2] == "Deeper"

    def test_empty_hierarchy_returns_empty(self):
        """Empty string returns ''."""
        from path_builder import _expand_studio_hierarchy

        result = _expand_studio_hierarchy("", " ")
        assert result == ""

    def test_single_segment_no_split(self):
        """'Brazzers' returns just 'Brazzers' (no os.sep)."""
        from path_builder import _expand_studio_hierarchy

        result = _expand_studio_hierarchy("Brazzers", " ")
        assert result == "Brazzers"
        assert os.sep not in result or os.sep == "/"  # Only "/" if that IS os.sep

    def test_segments_with_illegal_chars_sanitized(self):
        """'Mind:Geek/Bra*zzers' has illegal chars removed from each segment."""
        from path_builder import _expand_studio_hierarchy

        result = _expand_studio_hierarchy("Mind:Geek/Bra*zzers", " ")
        segments = result.split(os.sep)
        assert len(segments) == 2
        # Illegal chars replaced with separator (space), then sanitized
        assert ":" not in segments[0]
        assert "*" not in segments[1]

    def test_empty_segments_filtered(self):
        """'MindGeek//Deeper' (double slash) skips the empty segment."""
        from path_builder import _expand_studio_hierarchy

        result = _expand_studio_hierarchy("MindGeek//Deeper", " ")
        segments = result.split(os.sep)
        assert len(segments) == 2
        assert segments[0] == "MindGeek"
        assert segments[1] == "Deeper"


# =============================================================================
# _substitute_current_dir tests
# =============================================================================


class TestSubstituteCurrentDir:
    """Tests for _substitute_current_dir() - ^* replacement with current dir."""

    def test_replaces_caret_star(self):
        """Template '^*/$performer' with current path produces dir/$performer."""
        from path_builder import _substitute_current_dir

        result = _substitute_current_dir("^*/$performer", "/media/videos/scene.mp4")
        assert result == "/media/videos/$performer"

    def test_no_caret_star_returns_unchanged(self):
        """Template '$studio/$title' passes through unchanged."""
        from path_builder import _substitute_current_dir

        result = _substitute_current_dir("$studio/$title", "/media/videos/scene.mp4")
        assert result == "$studio/$title"

    def test_multiple_caret_star_all_replaced(self):
        """'^*/subfolder/^*' replaces both occurrences."""
        from path_builder import _substitute_current_dir

        result = _substitute_current_dir("^*/subfolder/^*", "/media/videos/scene.mp4")
        # Both ^* replaced with "/media/videos" (dirname of the file)
        # Second ^* starts with "/" so there's a double slash -- this is expected
        # and handled downstream by build_path's segment splitting
        assert result == "/media/videos/subfolder//media/videos"


# =============================================================================
# _deduplicate_consecutive tests
# =============================================================================


class TestDeduplicateConsecutive:
    """Tests for _deduplicate_consecutive() - consecutive folder dedup."""

    def test_removes_consecutive_duplicates(self):
        """['media', 'Deeper', 'Deeper', 'videos'] -> ['media', 'Deeper', 'videos']."""
        from path_builder import _deduplicate_consecutive

        result = _deduplicate_consecutive(["media", "Deeper", "Deeper", "videos"])
        assert result == ["media", "Deeper", "videos"]

    def test_non_consecutive_duplicates_kept(self):
        """['Deeper', 'media', 'Deeper'] is unchanged."""
        from path_builder import _deduplicate_consecutive

        result = _deduplicate_consecutive(["Deeper", "media", "Deeper"])
        assert result == ["Deeper", "media", "Deeper"]

    def test_empty_list(self):
        """[] returns []."""
        from path_builder import _deduplicate_consecutive

        result = _deduplicate_consecutive([])
        assert result == []

    def test_single_element(self):
        """['media'] returns ['media']."""
        from path_builder import _deduplicate_consecutive

        result = _deduplicate_consecutive(["media"])
        assert result == ["media"]

    def test_all_same(self):
        """['a', 'a', 'a'] returns ['a']."""
        from path_builder import _deduplicate_consecutive

        result = _deduplicate_consecutive(["a", "a", "a"])
        assert result == ["a"]


# =============================================================================
# _apply_performer_path_overrides tests
# =============================================================================


class TestApplyPerformerPathOverrides:
    """Tests for _apply_performer_path_overrides() - performer variable overrides for paths."""

    def _make_config(self, **path_overrides):
        """Helper to create a Config with PathManagementConfig overrides."""
        paths_config = replace(PathManagementConfig(), **path_overrides) if path_overrides else PathManagementConfig()
        return replace(Config(), paths=paths_config)

    def test_single_performer_in_path_takes_first(self):
        """When single_performer_in_path=True, only first performer is kept."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(single_performer_in_path=True, keep_existing_performer_folder=False)
        variables = {"performer": "Jane Doe, John Smith"}
        result = _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert result["performer"] == "Jane Doe"

    def test_single_performer_in_path_false_keeps_all(self):
        """When single_performer_in_path=False, all performers are kept."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(single_performer_in_path=False, keep_existing_performer_folder=False)
        variables = {"performer": "Jane Doe, John Smith"}
        result = _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert result["performer"] == "Jane Doe, John Smith"

    def test_no_performer_folder_substitutes_placeholder(self):
        """When no_performer_folder=True and performer is empty, sets to 'NoPerformer'."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(no_performer_folder=True, single_performer_in_path=False, keep_existing_performer_folder=False)
        variables = {"performer": ""}
        result = _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert result["performer"] == "NoPerformer"

    def test_no_performer_folder_false_keeps_empty(self):
        """When no_performer_folder=False and performer is empty, stays empty."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(no_performer_folder=False, single_performer_in_path=False, keep_existing_performer_folder=False)
        variables = {"performer": ""}
        result = _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert result["performer"] == ""

    def test_no_performer_folder_ignored_when_performer_exists(self):
        """When no_performer_folder=True but performer has value, performer unchanged."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(no_performer_folder=True, single_performer_in_path=False, keep_existing_performer_folder=False)
        variables = {"performer": "Jane Doe"}
        result = _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert result["performer"] == "Jane Doe"

    def test_keep_existing_performer_folder_uses_existing(self):
        """When keep_existing=True and path contains a performer, that performer is used."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(keep_existing_performer_folder=True, single_performer_in_path=False)
        # John Smith is in the path but not first in sort order
        variables = {"performer": "Jane Doe, John Smith"}
        result = _apply_performer_path_overrides(
            variables, config, "/media/John Smith/videos/scene.mp4"
        )
        assert result["performer"] == "John Smith"

    def test_keep_existing_performer_folder_false_ignores(self):
        """When keep_existing=False, first performer is used regardless of path."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(keep_existing_performer_folder=False, single_performer_in_path=True)
        variables = {"performer": "Jane Doe, John Smith"}
        result = _apply_performer_path_overrides(
            variables, config, "/media/John Smith/videos/scene.mp4"
        )
        assert result["performer"] == "Jane Doe"

    def test_does_not_mutate_input_dict(self):
        """Original variables dict is unchanged after calling the function."""
        from path_builder import _apply_performer_path_overrides

        config = self._make_config(single_performer_in_path=True, keep_existing_performer_folder=False)
        variables = {"performer": "Jane Doe, John Smith", "title": "Scene"}
        original_performer = variables["performer"]
        original_title = variables["title"]
        _apply_performer_path_overrides(variables, config, "/media/videos/scene.mp4")
        assert variables["performer"] == original_performer
        assert variables["title"] == original_title


# =============================================================================
# build_path tests
# =============================================================================


class TestBuildPath:
    """Tests for build_path() - path construction pipeline."""

    def _make_config(self, text_overrides=None, path_overrides=None):
        """Helper to create a Config with TextConfig and PathManagement overrides."""
        text_config = replace(TextConfig(), **(text_overrides or {}))
        paths_config = replace(PathManagementConfig(), **(path_overrides or {}))
        return replace(Config(), text=text_config, paths=paths_config)

    def test_basic_path_from_template(self):
        """Template '$studio/$title' with variables produces sanitized path."""
        from path_builder import build_path

        config = self._make_config()
        variables = {"studio": "Deeper", "title": "Scene Title"}
        result = build_path("$studio/$title", variables, config, "/media/videos/scene.mp4")
        parts = result.split(os.sep)
        assert "Deeper" in parts
        assert "Scene Title" in parts

    def test_studio_hierarchy_expansion(self):
        """Template '$studio_hierarchy/$title' expands hierarchy into nested folders."""
        from path_builder import build_path

        config = self._make_config()
        variables = {"studio_hierarchy": "MindGeek/Brazzers/Deeper", "title": "Scene"}
        result = build_path("$studio_hierarchy/$title", variables, config, "/media/videos/scene.mp4")
        parts = result.split(os.sep)
        assert "MindGeek" in parts
        assert "Brazzers" in parts
        assert "Deeper" in parts
        assert "Scene" in parts

    def test_caret_star_substitution(self):
        """Template '^*/$performer' replaces ^* with current directory."""
        from path_builder import build_path

        config = self._make_config(path_overrides={"keep_existing_performer_folder": False, "single_performer_in_path": False})
        variables = {"performer": "Jane Doe"}
        result = build_path("^*/$performer", variables, config, "/media/videos/scene.mp4")
        # Should contain the current directory parts and performer
        assert "Jane Doe" in result
        assert "media" in result
        assert "videos" in result

    def test_absolute_path_preserved(self):
        """Template starting with '/' produces absolute path (leading separator)."""
        from path_builder import build_path

        config = self._make_config()
        variables = {"studio": "Deeper"}
        result = build_path("/$studio", variables, config, "/media/videos/scene.mp4")
        assert result.startswith(os.sep)

    def test_empty_segments_removed(self):
        """Segments that render to empty strings are dropped from path."""
        from path_builder import build_path

        config = self._make_config()
        variables = {"studio": "Deeper", "performer": "", "title": "Scene"}
        result = build_path("$studio/$performer/$title", variables, config, "/media/videos/scene.mp4")
        parts = result.split(os.sep)
        # performer is empty, so it should NOT appear as an empty segment
        assert "" not in parts

    def test_consecutive_dedup_when_enabled(self):
        """With prevent_consecutive_folders=True, duplicate consecutive folders removed."""
        from path_builder import build_path

        config = self._make_config(path_overrides={"prevent_consecutive_folders": True})
        variables = {"studio": "Deeper", "title": "Deeper"}
        result = build_path("$studio/$title", variables, config, "/media/videos/scene.mp4")
        parts = result.split(os.sep)
        # Should have only one "Deeper" since they are consecutive
        consecutive_deeper = sum(1 for i in range(len(parts) - 1) if parts[i] == parts[i + 1] == "Deeper")
        assert consecutive_deeper == 0

    def test_consecutive_dedup_skipped_when_disabled(self):
        """With prevent_consecutive_folders=False, duplicates are kept."""
        from path_builder import build_path

        config = self._make_config(path_overrides={"prevent_consecutive_folders": False})
        variables = {"studio": "Deeper", "title": "Deeper"}
        result = build_path("$studio/$title", variables, config, "/media/videos/scene.mp4")
        parts = result.split(os.sep)
        # Both "Deeper" segments should be present
        assert parts.count("Deeper") == 2

    def test_performer_path_overrides_applied(self):
        """single_performer_in_path affects the path output."""
        from path_builder import build_path

        config = self._make_config(path_overrides={"single_performer_in_path": True, "keep_existing_performer_folder": False})
        variables = {"performer": "Jane Doe, John Smith"}
        result = build_path("$performer", variables, config, "/media/videos/scene.mp4")
        # Only first performer should appear in path
        assert "Jane Doe" in result
        assert "John Smith" not in result

    def test_template_uses_forward_slash_convention(self):
        """Templates use '/' as separator; output uses os.sep."""
        from path_builder import build_path

        config = self._make_config()
        variables = {"studio": "Deeper", "title": "Scene"}
        result = build_path("$studio/$title", variables, config, "/media/videos/scene.mp4")
        # Output should use os.sep
        assert os.sep.join(["Deeper", "Scene"]) in result


# =============================================================================
# _reduce_path_length tests
# =============================================================================


class TestReducePathLength:
    """Tests for _reduce_path_length() - iterative field reduction for path length."""

    def _make_config(self, max_length=240, length_reduction_order=None, text_overrides=None, path_overrides=None):
        """Helper to create a Config with path and text overrides."""
        path_kw = {"max_length": max_length}
        if length_reduction_order is not None:
            path_kw["length_reduction_order"] = length_reduction_order
        if path_overrides:
            path_kw.update(path_overrides)
        paths_config = replace(PathManagementConfig(), **path_kw)
        text_config = replace(TextConfig(), **(text_overrides or {}))
        return replace(Config(), paths=paths_config, text=text_config)

    def test_path_within_limit_returns_unchanged(self):
        """When combined filename+path is under max_length, returns original filename and path."""
        from path_builder import _reduce_path_length

        config = self._make_config(max_length=240, length_reduction_order=["$studio", "$performer"])
        variables = {"title": "Short", "studio": "S", "performer": "P"}
        result = _reduce_path_length(
            variables, config, "$title", "$studio/$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        assert isinstance(result, tuple)
        assert len(result) == 2
        filename, path = result
        # Path is short enough, so both should be non-empty with variables intact
        assert "Short" in filename
        assert "S" in path or "P" in path

    def test_reduces_first_field_to_fit(self):
        """When path exceeds limit, the first field in reduction_order is emptied."""
        from path_builder import _reduce_path_length

        # Create a config with a very short max_length so that removing $tags makes it fit
        variables = {
            "title": "Scene",
            "tags": "LongTagValue",
            "performer": "Jane",
        }
        # "LongTagValue/Jane/Scene.mp4" = 28 chars -> set max to 20 to force reduction
        config = self._make_config(
            max_length=20,
            length_reduction_order=["$tags", "$performer"],
        )
        filename, path = _reduce_path_length(
            variables, config, "$title", "$tags/$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        # After reducing $tags to "", the tag segment should be gone from the path
        # (process_text on empty renders to empty, which build_path skips)
        assert "LongTagValue" not in path

    def test_reduces_multiple_fields_iteratively(self):
        """When reducing one field is insufficient, multiple fields are reduced."""
        from path_builder import _reduce_path_length

        variables = {
            "title": "T",
            "tags": "TagsValue",
            "performer": "PerformerName",
            "studio": "StudioName",
        }
        # Very short max to force multiple reductions
        config = self._make_config(
            max_length=15,
            length_reduction_order=["$tags", "$performer", "$studio"],
        )
        filename, path = _reduce_path_length(
            variables, config, "$title", "$tags/$performer/$studio",
            "s.mp4", "/m/s.mp4"
        )
        # All three should be reduced
        assert "TagsValue" not in path
        assert "PerformerName" not in path

    def test_does_not_mutate_original_variables(self):
        """The input variables dict is unchanged after reduction."""
        from path_builder import _reduce_path_length

        variables = {
            "title": "Scene",
            "tags": "SomeTags",
            "performer": "Jane",
        }
        original = dict(variables)
        config = self._make_config(
            max_length=10,
            length_reduction_order=["$tags", "$performer"],
        )
        _reduce_path_length(
            variables, config, "$title", "$tags/$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        assert variables == original

    def test_skips_already_empty_fields(self):
        """Fields that are already '' in variables are skipped."""
        from path_builder import _reduce_path_length

        variables = {
            "title": "Scene",
            "tags": "",
            "performer": "PerformerNameThatIsVeryLong",
        }
        config = self._make_config(
            max_length=25,
            length_reduction_order=["$tags", "$performer"],
        )
        filename, path = _reduce_path_length(
            variables, config, "$title", "$tags/$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        # tags was already empty; performer should be reduced
        assert "PerformerNameThatIsVeryLong" not in path

    def test_returns_best_effort_when_all_exhausted(self):
        """When all fields in reduction_order are removed and path still exceeds limit, returns whatever was generated."""
        from path_builder import _reduce_path_length

        variables = {
            "title": "ThisIsAVeryLongTitleThatExceedsEverything",
            "tags": "T",
            "performer": "P",
        }
        # max_length=5 is impossibly short
        config = self._make_config(
            max_length=5,
            length_reduction_order=["$tags", "$performer"],
        )
        result = _reduce_path_length(
            variables, config, "$title", "$tags/$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        # Should return a tuple, not crash
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_reduction_regenerates_both_filename_and_path(self):
        """After removing a field, BOTH filename and path are rebuilt."""
        from path_builder import _reduce_path_length

        variables = {
            "title": "Scene",
            "performer": "PerformerWithVeryLongName",
        }
        # Use performer in BOTH filename and path templates
        config = self._make_config(
            max_length=30,
            length_reduction_order=["$performer"],
        )
        filename, path = _reduce_path_length(
            variables, config, "$title $performer", "$performer",
            "scene.mp4", "/media/videos/scene.mp4"
        )
        # performer should be removed from BOTH filename and path
        assert "PerformerWithVeryLongName" not in filename
        assert "PerformerWithVeryLongName" not in path


# =============================================================================
# build_scene_output tests
# =============================================================================


class TestBuildSceneOutput:
    """Tests for build_scene_output() - top-level pipeline orchestrator."""

    def _make_config(self, filename_overrides=None, path_overrides=None,
                     text_overrides=None, paths_overrides=None):
        """Helper to create a Config with various section overrides."""
        filename_config = replace(FilenameConfig(), **(filename_overrides or {}))
        path_config = replace(PathConfig(), **(path_overrides or {}))
        text_config = replace(TextConfig(), **(text_overrides or {}))
        paths_config = replace(PathManagementConfig(), **(paths_overrides or {}))
        return replace(
            Config(),
            filename=filename_config,
            path=path_config,
            text=text_config,
            paths=paths_config,
        )

    def test_full_pipeline_produces_filename_and_path(self, full_scene):
        """A scene with files, title, studio, performer produces a (filename, path) tuple."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$date $title"},
            path_overrides={"use_default": True, "default": "$studio"},
        )
        result = build_scene_output(full_scene, config)
        assert result is not None
        assert isinstance(result, tuple)
        assert len(result) == 3
        filename, path, _matched_tag = result
        assert isinstance(filename, str)
        assert isinstance(path, str)
        assert len(filename) > 0
        assert len(path) > 0

    def test_scene_with_no_files_returns_none(self):
        """Scene dict with empty 'files' array returns None."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True},
            path_overrides={"use_default": True},
        )
        scene_no_files = {
            "id": "1",
            "title": "Test",
            "files": [],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene_no_files, config)
        assert result is None

    def test_scene_with_no_files_key_returns_none(self):
        """Scene dict with no 'files' key returns None."""
        from path_builder import build_scene_output

        config = self._make_config()
        scene_no_key = {"id": "1", "title": "Test"}
        result = build_scene_output(scene_no_key, config)
        assert result is None

    def test_no_matching_templates_keeps_original(self):
        """When no templates match, returns original filename and original directory."""
        from path_builder import build_scene_output

        # use_default=False for both, no tag/studio/path templates
        config = self._make_config(
            filename_overrides={"use_default": False},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "Test Scene",
            "files": [{"path": "/media/videos/original.mp4"}],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        assert filename == "original.mp4"
        assert path == "/media/videos"

    def test_field_transforms_applied_in_pipeline(self):
        """When config.text.field_whitespace_separator is set, variable values are transformed."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": False},
            text_overrides={"field_whitespace_separator": "_"},
        )
        scene = {
            "id": "1",
            "title": "Scene Title",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        # field_whitespace_separator should replace spaces with "_" in title
        assert "_" in filename

    def test_length_reduction_triggered_when_path_too_long(self):
        """With max_length very small, output path is shorter than unreduced version."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": True, "default": "$studio/$performer"},
            paths_overrides={
                "max_length": 30,
                "length_reduction_order": ["$performer", "$studio"],
                "keep_existing_performer_folder": False,
                "single_performer_in_path": False,
            },
        )
        scene = {
            "id": "1",
            "title": "Test",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": {"id": "1", "name": "VeryLongStudioName", "parent_studio": None},
            "tags": [],
            "performers": [
                {"id": "1", "name": "PerformerWithLongName", "gender": "FEMALE",
                 "favorite": False, "rating100": None, "stash_ids": []},
            ],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        full = os.path.join(path, filename)
        # The full path might still be longer than 30 (best-effort),
        # but some fields should have been reduced
        # Verify at least one field was removed
        assert "PerformerWithLongName" not in full or "VeryLongStudioName" not in full

    def test_pure_function_no_side_effects(self, full_scene):
        """Scene dict and Config are not mutated after calling build_scene_output."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$date $title"},
            path_overrides={"use_default": True, "default": "$studio"},
        )
        scene_copy = copy.deepcopy(full_scene)
        build_scene_output(full_scene, config)
        assert full_scene == scene_copy

    def test_only_filename_template_matched(self):
        """When only filename template matches, the path is the original directory."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "New Title",
            "files": [{"path": "/media/videos/old.mp4"}],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        assert "New Title" in filename or "New" in filename
        assert path == "/media/videos"

    def test_only_path_template_matched(self):
        """When only path template matches, the filename is the original filename."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": False},
            path_overrides={"use_default": True, "default": "$studio"},
        )
        scene = {
            "id": "1",
            "title": "Test",
            "files": [{"path": "/media/videos/original.mp4"}],
            "studio": {"id": "1", "name": "MyStudio", "parent_studio": None},
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        assert filename == "original.mp4"
        assert "MyStudio" in path

    def test_filename_template_with_path_template(self):
        """When both templates match, both filename and path are generated."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": True, "default": "$studio"},
        )
        scene = {
            "id": "1",
            "title": "New Title",
            "files": [{"path": "/media/videos/old.mp4"}],
            "studio": {"id": "1", "name": "MyStudio", "parent_studio": None},
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        assert "New Title" in filename or "New" in filename
        assert "MyStudio" in path

    def test_extension_preserved_through_full_pipeline(self):
        """A scene with a .mkv file produces output with .mkv extension."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "Test Scene",
            "files": [{"path": "/media/videos/movie.mkv"}],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, _matched_tag = result
        assert filename.endswith(".mkv")


# =============================================================================
# build_scene_output matched_tag tests
# =============================================================================


class TestBuildSceneOutputMatchedTag:
    """Tests for build_scene_output matched_tag return value and inverse_performer wiring."""

    def _make_config(self, filename_overrides=None, path_overrides=None,
                     text_overrides=None, paths_overrides=None, tag_options=None):
        """Helper to create a Config with various section overrides."""
        from config_loader import TagModifiers
        filename_config = replace(FilenameConfig(), **(filename_overrides or {}))
        path_config = replace(PathConfig(), **(path_overrides or {}))
        text_config = replace(TextConfig(), **(text_overrides or {}))
        paths_config = replace(PathManagementConfig(), **(paths_overrides or {}))
        return replace(
            Config(),
            filename=filename_config,
            path=path_config,
            text=text_config,
            paths=paths_config,
            tag_options=tag_options or {},
        )

    def test_returns_matched_tag_when_tag_template_matches(self):
        """When scene has tag 'JAV' and filename.tag_templates has 'JAV',
        build_scene_output returns a 3-tuple (filename, path, 'JAV')."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"tag_templates": {"JAV": "$title"}, "use_default": False},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "Test Scene",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": None,
            "tags": [{"id": "1", "name": "JAV"}],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        assert len(result) == 3, f"Expected 3-tuple, got {len(result)}-tuple"
        filename, path, matched_tag = result
        assert matched_tag == "JAV"

    def test_returns_none_matched_tag_when_no_tag_matches(self):
        """When scene matches via default template, matched_tag is None."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": True, "default": "$title"},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "Test Scene",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": {"id": "1", "name": "MyStudio", "parent_studio": None},
            "tags": [{"id": "1", "name": "SomeTag"}],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        assert len(result) == 3
        filename, path, matched_tag = result
        assert matched_tag is None

    def test_returns_none_matched_tag_when_no_template_matches(self):
        """When no template matches at all, returns (filename, path, None)."""
        from path_builder import build_scene_output

        config = self._make_config(
            filename_overrides={"use_default": False},
            path_overrides={"use_default": False},
        )
        scene = {
            "id": "1",
            "title": "Test Scene",
            "files": [{"path": "/media/videos/original.mp4"}],
            "studio": None,
            "tags": [],
            "performers": [],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        assert len(result) == 3
        filename, path, matched_tag = result
        assert matched_tag is None

    def test_inverse_performer_applied_when_modifier_set(self):
        """When tag_options has inverse_performer=True for matched tag 'JAV',
        performer 'Doe, Jane' appears as 'Jane Doe' in the generated filename."""
        from path_builder import build_scene_output
        from config_loader import TagModifiers

        config = self._make_config(
            filename_overrides={
                "tag_templates": {"JAV": "$performer $title"},
                "use_default": False,
            },
            path_overrides={"use_default": False},
            tag_options={"JAV": TagModifiers(inverse_performer=True)},
        )
        scene = {
            "id": "1",
            "title": "Test",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": None,
            "tags": [{"id": "1", "name": "JAV"}],
            "performers": [
                {"id": "1", "name": "Doe, Jane", "gender": "FEMALE",
                 "favorite": False, "rating100": None, "stash_ids": []},
            ],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, matched_tag = result
        assert "Jane Doe" in filename
        assert "Doe, Jane" not in filename

    def test_inverse_performer_not_applied_for_different_tag(self):
        """Scene matches tag 'Western' which does NOT have inverse_performer.
        Performer 'Doe, Jane' remains 'Doe, Jane' in output."""
        from path_builder import build_scene_output
        from config_loader import TagModifiers

        config = self._make_config(
            filename_overrides={
                "tag_templates": {"Western": "$performer $title"},
                "use_default": False,
            },
            path_overrides={"use_default": False},
            tag_options={"Western": TagModifiers(inverse_performer=False)},
        )
        scene = {
            "id": "1",
            "title": "Test",
            "files": [{"path": "/media/videos/scene.mp4"}],
            "studio": None,
            "tags": [{"id": "1", "name": "Western"}],
            "performers": [
                {"id": "1", "name": "Doe, Jane", "gender": "FEMALE",
                 "favorite": False, "rating100": None, "stash_ids": []},
            ],
        }
        result = build_scene_output(scene, config)
        assert result is not None
        filename, path, matched_tag = result
        # Performer name should remain in original format (but note: remove_chars
        # default includes comma, so "Doe, Jane" may have the comma removed by
        # text processing. The key assertion is that it does NOT get inverted.)
        # We verify "Jane Doe" is NOT in the filename when inverse is off.
        assert "Jane Doe" not in filename
