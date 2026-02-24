"""Tests for metadata_extractor helper functions.

TDD RED phase: these tests define the expected behavior for all helper
functions. Each function must return str or dict[str, str], never None.
"""

import pytest

from metadata_extractor import (
    _safe_str,
    _get_nested,
    _get_fingerprint,
    _extract_date_fields,
    _map_resolution,
    _format_rating,
    _extract_groups,
    _extract_tags,
    _extract_stash_ids,
    _extract_technical,
    _sort_performers,
    _extract_performers,
    _build_studio_hierarchy,
    _extract_studio,
    extract_metadata,
    TEMPLATE_VARIABLES,
)
from config_loader import Config, FormattingConfig, TagConfig


# =============================================================================
# _safe_str
# =============================================================================


class TestSafeStr:
    """Tests for _safe_str: convert any value to string, None -> ''."""

    def test_none_returns_empty(self):
        assert _safe_str(None) == ""

    def test_string_passthrough(self):
        assert _safe_str("hello") == "hello"

    def test_empty_string_passthrough(self):
        assert _safe_str("") == ""

    def test_int_converts(self):
        assert _safe_str(42) == "42"

    def test_float_converts(self):
        assert _safe_str(3.14) == "3.14"

    def test_bool_converts(self):
        assert _safe_str(True) == "True"

    def test_zero_converts(self):
        assert _safe_str(0) == "0"


# =============================================================================
# _get_nested
# =============================================================================


class TestGetNested:
    """Tests for _get_nested: safely traverse nested dicts."""

    def test_single_key_found(self):
        assert _get_nested({"a": "val"}, "a") == "val"

    def test_single_key_missing(self):
        assert _get_nested({"a": "val"}, "b") == ""

    def test_nested_two_levels(self):
        data = {"a": {"b": "deep"}}
        assert _get_nested(data, "a", "b") == "deep"

    def test_nested_missing_intermediate(self):
        data = {"a": "not_dict"}
        assert _get_nested(data, "a", "b") == ""

    def test_nested_none_intermediate(self):
        data = {"a": None}
        assert _get_nested(data, "a", "b") == ""

    def test_empty_dict(self):
        assert _get_nested({}, "a") == ""

    def test_custom_default(self):
        assert _get_nested({}, "a", default="N/A") == "N/A"

    def test_int_value_converted(self):
        result = _get_nested({"a": 42}, "a")
        assert result == "42"
        assert isinstance(result, str)

    def test_three_levels(self):
        data = {"a": {"b": {"c": "found"}}}
        assert _get_nested(data, "a", "b", "c") == "found"


# =============================================================================
# _get_fingerprint
# =============================================================================


class TestGetFingerprint:
    """Tests for _get_fingerprint: extract fingerprint from files[0].fingerprints[]."""

    def test_found_oshash(self, full_scene):
        assert _get_fingerprint(full_scene, "oshash") == "abc123hash"

    def test_found_md5(self, full_scene):
        assert _get_fingerprint(full_scene, "md5") == "def456md5"

    def test_not_found_type(self, full_scene):
        assert _get_fingerprint(full_scene, "nonexistent") == ""

    def test_empty_files(self, bare_scene):
        assert _get_fingerprint(bare_scene, "oshash") == ""

    def test_no_files_key(self):
        assert _get_fingerprint({}, "oshash") == ""

    def test_files_none(self):
        assert _get_fingerprint({"files": None}, "oshash") == ""

    def test_empty_fingerprints(self):
        scene = {"files": [{"fingerprints": []}]}
        assert _get_fingerprint(scene, "oshash") == ""

    def test_flattened_format_fallback(self):
        """stashapp-tools may put fingerprints as direct keys on file dict."""
        scene = {"files": [{"fingerprints": [], "oshash": "flat-hash"}]}
        assert _get_fingerprint(scene, "oshash") == "flat-hash"

    def test_fingerprints_preferred_over_flattened(self):
        """Nested fingerprints array should be checked before flattened keys."""
        scene = {
            "files": [
                {
                    "fingerprints": [{"type": "oshash", "value": "nested-hash"}],
                    "oshash": "flat-hash",
                }
            ]
        }
        assert _get_fingerprint(scene, "oshash") == "nested-hash"


# =============================================================================
# _extract_date_fields
# =============================================================================


class TestExtractDateFields:
    """Tests for _extract_date_fields: parse date with multi-format fallback."""

    def test_full_iso_date(self, make_formatting_config):
        fmt = make_formatting_config(date_format="%Y-%m-%d")
        result = _extract_date_fields("2024-01-15", fmt)
        assert result["year"] == "2024"
        assert result["date_format"] == "2024-01-15"

    def test_full_iso_custom_format(self, make_formatting_config):
        fmt = make_formatting_config(date_format="%d/%m/%Y")
        result = _extract_date_fields("2024-01-15", fmt)
        assert result["year"] == "2024"
        assert result["date_format"] == "15/01/2024"

    def test_year_only(self, make_formatting_config):
        fmt = make_formatting_config()
        result = _extract_date_fields("2024", fmt)
        assert result["year"] == "2024"
        assert result["date_format"] == ""

    def test_empty_string(self, make_formatting_config):
        fmt = make_formatting_config()
        result = _extract_date_fields("", fmt)
        assert result["year"] == ""
        assert result["date_format"] == ""

    def test_malformed_date(self, make_formatting_config):
        fmt = make_formatting_config()
        result = _extract_date_fields("not-a-date", fmt)
        assert result["year"] == ""
        assert result["date_format"] == ""

    def test_no_exception_on_garbage(self, make_formatting_config):
        fmt = make_formatting_config()
        # Should not raise any exception
        result = _extract_date_fields("xyz", fmt)
        assert isinstance(result, dict)
        assert result["year"] == ""

    def test_partial_date(self, make_formatting_config):
        """A date like '2024-01' should extract year but not full date_format."""
        fmt = make_formatting_config()
        result = _extract_date_fields("2024-01", fmt)
        assert result["year"] == "2024"
        assert result["date_format"] == ""

    def test_return_values_are_strings(self, make_formatting_config):
        fmt = make_formatting_config()
        result = _extract_date_fields("2024-01-15", fmt)
        for val in result.values():
            assert isinstance(val, str)


# =============================================================================
# _map_resolution
# =============================================================================


class TestMapResolution:
    """Tests for _map_resolution: map pixel dimensions to labels."""

    def test_1080p_hd(self):
        height, res = _map_resolution(1080, 1920)
        assert height == "1080p"
        assert res == "HD"

    def test_720p_hd(self):
        height, res = _map_resolution(720, 1280)
        assert height == "720p"
        assert res == "HD"

    def test_4k_uhd(self):
        height, res = _map_resolution(2160, 3840)
        assert height == "4k"
        assert res == "UHD"

    def test_8k_uhd(self):
        height, res = _map_resolution(4320, 7680)
        assert height == "8k"
        assert res == "UHD"

    def test_6k_uhd(self):
        height, res = _map_resolution(3384, 6016)
        assert height == "6k"
        assert res == "UHD"

    def test_5k_uhd(self):
        height, res = _map_resolution(2880, 5120)
        assert height == "5k"
        assert res == "UHD"

    def test_480p_sd(self):
        height, res = _map_resolution(480, 640)
        assert height == "480p"
        assert res == "SD"

    def test_360p_sd(self):
        height, res = _map_resolution(360, 640)
        assert height == "360p"
        assert res == "SD"

    def test_vertical_video(self):
        """Height > width should produce VERTICAL category."""
        height, res = _map_resolution(1920, 1080)
        assert height == "1920p"
        assert res == "VERTICAL"

    def test_vertical_4k(self):
        height, res = _map_resolution(3840, 2160)
        assert height == "3840p"
        assert res == "VERTICAL"

    def test_zero_dimensions(self):
        height, res = _map_resolution(0, 0)
        assert height == "0p"
        assert res == "SD"

    def test_return_types(self):
        height, res = _map_resolution(1080, 1920)
        assert isinstance(height, str)
        assert isinstance(res, str)


# =============================================================================
# _format_rating
# =============================================================================


class TestFormatRating:
    """Tests for _format_rating: format rating100 int using config format."""

    def test_valid_rating_default_format(self, make_formatting_config):
        fmt = make_formatting_config(rating_format="{}")
        assert _format_rating(80, fmt) == "80"

    def test_none_rating(self, make_formatting_config):
        fmt = make_formatting_config()
        assert _format_rating(None, fmt) == ""

    def test_zero_rating(self, make_formatting_config):
        fmt = make_formatting_config()
        assert _format_rating(0, fmt) == "0"

    def test_custom_format(self, make_formatting_config):
        fmt = make_formatting_config(rating_format="{}/100")
        assert _format_rating(85, fmt) == "85/100"

    def test_return_type(self, make_formatting_config):
        fmt = make_formatting_config()
        result = _format_rating(50, fmt)
        assert isinstance(result, str)


# =============================================================================
# _extract_groups
# =============================================================================


class TestExtractGroups:
    """Tests for _extract_groups: extract movie/group variables with fallback."""

    def test_groups_key_v027(self):
        """Stash v0.27+ uses 'groups' key with 'group' sub-key."""
        scene = {
            "groups": [
                {
                    "group": {"name": "Movie Title", "date": "2024-01-01"},
                    "scene_index": 3,
                }
            ]
        }
        result = _extract_groups(scene)
        assert result["movie_title"] == "Movie Title"
        assert result["movie_year"] == "2024"
        assert result["movie_scene"] == "scene 3"

    def test_movies_fallback_v026(self):
        """Stash v0.26- uses 'movies' key with 'movie' sub-key."""
        scene = {
            "movies": [
                {
                    "movie": {"name": "Old Movie", "date": "2023-06-15"},
                    "scene_index": 1,
                }
            ]
        }
        result = _extract_groups(scene)
        assert result["movie_title"] == "Old Movie"
        assert result["movie_year"] == "2023"
        assert result["movie_scene"] == "scene 1"

    def test_empty_groups(self):
        scene = {"groups": []}
        result = _extract_groups(scene)
        assert result["movie_title"] == ""
        assert result["movie_year"] == ""
        assert result["movie_scene"] == ""

    def test_no_groups_or_movies(self):
        scene = {}
        result = _extract_groups(scene)
        assert result["movie_title"] == ""
        assert result["movie_year"] == ""
        assert result["movie_scene"] == ""

    def test_scene_index_none(self):
        scene = {
            "groups": [
                {
                    "group": {"name": "No Index", "date": "2024-03-01"},
                    "scene_index": None,
                }
            ]
        }
        result = _extract_groups(scene)
        assert result["movie_title"] == "No Index"
        assert result["movie_scene"] == ""

    def test_group_no_date(self):
        scene = {
            "groups": [
                {
                    "group": {"name": "Dateless", "date": None},
                    "scene_index": 1,
                }
            ]
        }
        result = _extract_groups(scene)
        assert result["movie_year"] == ""

    def test_groups_preferred_over_movies(self):
        """When both keys exist, 'groups' takes priority."""
        scene = {
            "groups": [
                {"group": {"name": "New Name"}, "scene_index": None}
            ],
            "movies": [
                {"movie": {"name": "Old Name"}, "scene_index": None}
            ],
        }
        result = _extract_groups(scene)
        assert result["movie_title"] == "New Name"

    def test_all_values_are_strings(self, full_scene):
        result = _extract_groups(full_scene)
        for val in result.values():
            assert isinstance(val, str), f"Value {val!r} is not str"


# =============================================================================
# _extract_tags
# =============================================================================


class TestExtractTags:
    """Tests for _extract_tags: filter and join tag names."""

    def test_no_filter(self, make_tag_config):
        config = make_tag_config()
        tags = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        result = _extract_tags(tags, config)
        assert result["tags"] == "A B C"

    def test_whitelist_filter(self, make_tag_config):
        config = make_tag_config(whitelist=["A", "C"])
        tags = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        result = _extract_tags(tags, config)
        assert result["tags"] == "A C"

    def test_blacklist_filter(self, make_tag_config):
        config = make_tag_config(blacklist=["B"])
        tags = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        result = _extract_tags(tags, config)
        assert result["tags"] == "A C"

    def test_whitelist_and_blacklist(self, make_tag_config):
        """Whitelist applied first, then blacklist removes from whitelist result."""
        config = make_tag_config(whitelist=["A", "B", "C"], blacklist=["B"])
        tags = [{"name": "A"}, {"name": "B"}, {"name": "C"}]
        result = _extract_tags(tags, config)
        assert result["tags"] == "A C"

    def test_custom_separator(self, make_tag_config):
        config = make_tag_config(separator=", ")
        tags = [{"name": "X"}, {"name": "Y"}]
        result = _extract_tags(tags, config)
        assert result["tags"] == "X, Y"

    def test_empty_tags(self, make_tag_config):
        config = make_tag_config()
        result = _extract_tags([], config)
        assert result["tags"] == ""

    def test_return_type(self, make_tag_config):
        config = make_tag_config()
        result = _extract_tags([{"name": "A"}], config)
        assert isinstance(result["tags"], str)


# =============================================================================
# _extract_stash_ids
# =============================================================================


class TestExtractStashIds:
    """Tests for _extract_stash_ids: extract scene stash ID."""

    def test_stash_id_present(self):
        scene = {
            "stash_ids": [
                {"endpoint": "https://stashdb.org/graphql", "stash_id": "uuid-123"}
            ]
        }
        result = _extract_stash_ids(scene, {})
        assert result["stashid_scene"] == "uuid-123"

    def test_empty_stash_ids(self):
        scene = {"stash_ids": []}
        result = _extract_stash_ids(scene, {})
        assert result["stashid_scene"] == ""

    def test_no_stash_ids_key(self):
        scene = {}
        result = _extract_stash_ids(scene, {})
        assert result["stashid_scene"] == ""

    def test_stash_ids_none(self):
        scene = {"stash_ids": None}
        result = _extract_stash_ids(scene, {})
        assert result["stashid_scene"] == ""

    def test_return_type(self, full_scene):
        result = _extract_stash_ids(full_scene, {})
        assert isinstance(result["stashid_scene"], str)


# =============================================================================
# _extract_technical
# =============================================================================


class TestExtractTechnical:
    """Tests for _extract_technical: extract technical video fields."""

    def test_full_scene(self, full_scene):
        result = _extract_technical(full_scene)
        assert result["height"] == "1080p"
        assert result["resolution"] == "HD"
        assert result["video_codec"] == "H264"
        assert result["audio_codec"] == "AAC"
        assert result["duration"] == "1800.5"
        assert result["bitrate"] == "5.0"

    def test_empty_files(self, bare_scene):
        result = _extract_technical(bare_scene)
        assert result["height"] == ""
        assert result["resolution"] == ""
        assert result["video_codec"] == ""
        assert result["audio_codec"] == ""
        assert result["duration"] == ""
        assert result["bitrate"] == ""

    def test_missing_fields(self):
        """File dict with some fields missing."""
        scene = {"files": [{"width": 1920, "height": 1080}]}
        result = _extract_technical(scene)
        assert result["height"] == "1080p"
        assert result["resolution"] == "HD"
        assert result["video_codec"] == ""
        assert result["audio_codec"] == ""
        assert result["duration"] == ""
        assert result["bitrate"] == ""

    def test_all_values_are_strings(self, full_scene):
        result = _extract_technical(full_scene)
        for key, val in result.items():
            assert isinstance(val, str), f"{key}={val!r} is not str"

    def test_codec_uppercase(self):
        scene = {
            "files": [
                {
                    "video_codec": "hevc",
                    "audio_codec": "opus",
                    "width": 1920,
                    "height": 1080,
                }
            ]
        }
        result = _extract_technical(scene)
        assert result["video_codec"] == "HEVC"
        assert result["audio_codec"] == "OPUS"

    def test_bitrate_rounding(self):
        """Bitrate in bps divided by 1_000_000 and rounded to 2 decimals."""
        scene = {
            "files": [
                {
                    "bit_rate": 12345678,
                    "width": 3840,
                    "height": 2160,
                }
            ]
        }
        result = _extract_technical(scene)
        assert result["bitrate"] == "12.35"

    def test_no_files_key(self):
        result = _extract_technical({})
        assert result["height"] == ""
        assert result["resolution"] == ""


# =============================================================================
# _sort_performers
# =============================================================================


class TestSortPerformers:
    """Tests for _sort_performers: sort performer dicts by 6 modes with ID tiebreaker."""

    @pytest.fixture
    def performers(self):
        """Return a list of performers with varied attributes for sorting tests."""
        return [
            {
                "id": "10",
                "name": "Charlie",
                "gender": "FEMALE",
                "favorite": False,
                "rating100": 70,
                "stash_ids": [{"stash_id": "sid-c"}],
            },
            {
                "id": "2",
                "name": "Alice",
                "gender": "FEMALE",
                "favorite": True,
                "rating100": 90,
                "stash_ids": [{"stash_id": "sid-a"}],
            },
            {
                "id": "5",
                "name": "Bob",
                "gender": "MALE",
                "favorite": False,
                "rating100": 90,
                "stash_ids": [{"stash_id": "sid-b"}],
            },
            {
                "id": "7",
                "name": "Diana",
                "gender": "FEMALE",
                "favorite": True,
                "rating100": 80,
                "stash_ids": [],
            },
        ]

    def test_sort_by_id_numeric(self, performers):
        """Sort by ID ascending numerically (2 before 5 before 7 before 10)."""
        result = _sort_performers(performers, "id")
        ids = [p["id"] for p in result]
        assert ids == ["2", "5", "7", "10"]

    def test_sort_by_id_numeric_not_string(self):
        """Verify numeric order: id '2' sorts before id '10' (not string order)."""
        perfs = [{"id": "10", "name": "A"}, {"id": "2", "name": "B"}]
        result = _sort_performers(perfs, "id")
        assert [p["id"] for p in result] == ["2", "10"]

    def test_sort_by_name_alphabetical(self, performers):
        """Sort by name alphabetically."""
        result = _sort_performers(performers, "name")
        names = [p["name"] for p in result]
        assert names == ["Alice", "Bob", "Charlie", "Diana"]

    def test_sort_by_name_id_tiebreaker(self):
        """Same name: tiebreak by ID ascending."""
        perfs = [
            {"id": "5", "name": "Same"},
            {"id": "2", "name": "Same"},
        ]
        result = _sort_performers(perfs, "name")
        assert [p["id"] for p in result] == ["2", "5"]

    def test_sort_by_rating_descending(self, performers):
        """Sort by rating100 descending, then name alpha, then ID."""
        result = _sort_performers(performers, "rating")
        # Alice (90) and Bob (90) tie; Alice < Bob alpha -> Alice first
        # Then Diana (80), then Charlie (70)
        names = [p["name"] for p in result]
        assert names == ["Alice", "Bob", "Diana", "Charlie"]

    def test_sort_by_rating_none_rating(self):
        """Performers with None rating100 treated as 0."""
        perfs = [
            {"id": "1", "name": "A", "rating100": None},
            {"id": "2", "name": "B", "rating100": 50},
        ]
        result = _sort_performers(perfs, "rating")
        assert [p["name"] for p in result] == ["B", "A"]

    def test_sort_by_favorite(self, performers):
        """Sort by favorite (True first), then name alpha, then ID."""
        result = _sort_performers(performers, "favorite")
        # Favorites: Alice, Diana (alpha order)
        # Non-favorites: Bob, Charlie (alpha order)
        names = [p["name"] for p in result]
        assert names == ["Alice", "Diana", "Bob", "Charlie"]

    def test_sort_by_mix(self, performers):
        """Sort by favorite first, then rating desc, then name alpha, then ID."""
        result = _sort_performers(performers, "mix")
        # Favorites: Alice (90), Diana (80) -> by rating desc -> Alice first
        # Non-favorites: Bob (90), Charlie (70) -> by rating desc -> Bob first
        names = [p["name"] for p in result]
        assert names == ["Alice", "Diana", "Bob", "Charlie"]

    def test_sort_by_mix_same_rating(self):
        """Within same favorite group and same rating, sort by name alpha."""
        perfs = [
            {"id": "5", "name": "Zoe", "favorite": False, "rating100": 80},
            {"id": "3", "name": "Amy", "favorite": False, "rating100": 80},
        ]
        result = _sort_performers(perfs, "mix")
        assert [p["name"] for p in result] == ["Amy", "Zoe"]

    def test_sort_by_mixid(self, performers):
        """Sort by favorite first, then rating desc, then ID (no name sort)."""
        result = _sort_performers(performers, "mixid")
        # Favorites: Alice (id=2, rating=90), Diana (id=7, rating=80)
        #   -> by rating desc -> Alice (90) first, Diana (80) second
        # Non-favorites: Bob (id=5, rating=90), Charlie (id=10, rating=70)
        #   -> by rating desc -> Bob (90) first, Charlie (70) second
        names = [p["name"] for p in result]
        assert names == ["Alice", "Diana", "Bob", "Charlie"]

    def test_sort_by_mixid_same_rating(self):
        """Within same favorite group and same rating, sort by ID (not name)."""
        perfs = [
            {"id": "5", "name": "Zoe", "favorite": False, "rating100": 80},
            {"id": "3", "name": "Amy", "favorite": False, "rating100": 80},
        ]
        result = _sort_performers(perfs, "mixid")
        # Same rating, tiebreak by ID: 3 < 5
        assert [p["name"] for p in result] == ["Amy", "Zoe"]

    def test_unrecognized_sort_mode(self, performers):
        """Unrecognized sort mode returns list unchanged."""
        original_ids = [p["id"] for p in performers]
        result = _sort_performers(performers, "unknown_mode")
        assert [p["id"] for p in result] == original_ids

    def test_empty_list(self):
        """Empty list returns empty list."""
        result = _sort_performers([], "name")
        assert result == []


# =============================================================================
# _extract_performers
# =============================================================================


class TestExtractPerformers:
    """Tests for _extract_performers: full performer extraction pipeline."""

    @pytest.fixture
    def performers(self):
        """Return a list of performers for extraction tests."""
        return [
            {
                "id": "1",
                "name": "Alice",
                "gender": "FEMALE",
                "favorite": True,
                "rating100": 90,
                "stash_ids": [{"stash_id": "sid-alice"}],
            },
            {
                "id": "2",
                "name": "Bob",
                "gender": "MALE",
                "favorite": False,
                "rating100": 70,
                "stash_ids": [{"stash_id": "sid-bob"}],
            },
            {
                "id": "3",
                "name": "Charlie",
                "gender": "FEMALE",
                "favorite": False,
                "rating100": 80,
                "stash_ids": [{"stash_id": "sid-charlie"}],
            },
        ]

    def test_empty_performers(self, make_performer_config):
        """Empty performers list returns empty strings."""
        config = make_performer_config()
        result = _extract_performers([], config)
        assert result["performer"] == ""
        assert result["stashid_performer"] == ""

    def test_basic_extraction_default_sort(self, performers, make_performer_config):
        """Default sort (id) with default limit (3) returns all 3 performers."""
        config = make_performer_config(sort="id", limit=3)
        result = _extract_performers(performers, config)
        assert result["performer"] == "Alice Bob Charlie"

    def test_custom_separator(self, performers, make_performer_config):
        """Performer names joined with custom separator."""
        config = make_performer_config(sort="id", limit=3, separator=", ")
        result = _extract_performers(performers, config)
        assert result["performer"] == "Alice, Bob, Charlie"

    def test_gender_filtering_exclude_male(self, performers, make_performer_config):
        """Filter out MALE gender performers."""
        config = make_performer_config(sort="id", limit=3, ignore_gender=["MALE"])
        result = _extract_performers(performers, config)
        assert result["performer"] == "Alice Charlie"

    def test_gender_filtering_exclude_undefined(self, make_performer_config):
        """Filter out performers with None gender when UNDEFINED is in ignore_gender."""
        perfs = [
            {"id": "1", "name": "Known", "gender": "FEMALE"},
            {"id": "2", "name": "Unknown", "gender": None},
        ]
        config = make_performer_config(
            sort="id", limit=10, ignore_gender=["UNDEFINED"]
        )
        result = _extract_performers(perfs, config)
        assert result["performer"] == "Known"

    def test_limit_keep_up_to_limit_true(self, performers, make_performer_config):
        """3 performers, limit 2, keep_up_to_limit=True -> first 2 kept."""
        config = make_performer_config(
            sort="id", limit=2, keep_up_to_limit=True
        )
        result = _extract_performers(performers, config)
        assert result["performer"] == "Alice Bob"

    def test_limit_keep_up_to_limit_false(self, performers, make_performer_config):
        """3 performers, limit 2, keep_up_to_limit=False -> empty result."""
        config = make_performer_config(
            sort="id", limit=2, keep_up_to_limit=False
        )
        result = _extract_performers(performers, config)
        assert result["performer"] == ""

    def test_limit_not_exceeded(self, performers, make_performer_config):
        """3 performers, limit 3 -> all kept (limit not exceeded)."""
        config = make_performer_config(sort="id", limit=3)
        result = _extract_performers(performers, config)
        assert result["performer"] == "Alice Bob Charlie"

    def test_stash_ids_joined(self, performers, make_performer_config):
        """Performer stash IDs joined with separator."""
        config = make_performer_config(sort="id", limit=3)
        result = _extract_performers(performers, config)
        assert result["stashid_performer"] == "sid-alice sid-bob sid-charlie"

    def test_stash_ids_missing(self, make_performer_config):
        """Performers without stash_ids are skipped in stashid_performer."""
        perfs = [
            {"id": "1", "name": "A", "stash_ids": [{"stash_id": "sid-a"}]},
            {"id": "2", "name": "B", "stash_ids": []},
            {"id": "3", "name": "C"},
        ]
        config = make_performer_config(sort="id", limit=10)
        result = _extract_performers(perfs, config)
        assert result["performer"] == "A B C"
        assert result["stashid_performer"] == "sid-a"

    def test_all_values_are_strings(self, performers, make_performer_config):
        """All returned values must be strings, never None."""
        config = make_performer_config(sort="name", limit=3)
        result = _extract_performers(performers, config)
        for key, val in result.items():
            assert isinstance(val, str), f"{key}={val!r} is not str"

    def test_sort_applied_before_limit(self, make_performer_config):
        """Sort is applied before limit truncation."""
        perfs = [
            {"id": "3", "name": "Charlie"},
            {"id": "1", "name": "Alice"},
            {"id": "2", "name": "Bob"},
        ]
        config = make_performer_config(
            sort="name", limit=2, keep_up_to_limit=True
        )
        result = _extract_performers(perfs, config)
        # Sorted by name: Alice, Bob, Charlie -> limit 2 -> Alice, Bob
        assert result["performer"] == "Alice Bob"


# =============================================================================
# _build_studio_hierarchy
# =============================================================================


class TestBuildStudioHierarchy:
    """Tests for _build_studio_hierarchy: walk parent_studio chain with cycle detection."""

    def test_single_studio_no_parent(self):
        """Studio with no parent returns single-element list."""
        studio = {"id": "1", "name": "Leaf Studio", "parent_studio": None}
        result = _build_studio_hierarchy(studio, 0)
        assert result == ["Leaf Studio"]

    def test_studio_with_one_parent(self):
        """Studio with one parent returns [parent, child] (root-to-leaf)."""
        studio = {
            "id": "2",
            "name": "Child",
            "parent_studio": {
                "id": "1",
                "name": "Parent",
                "parent_studio": None,
            },
        }
        result = _build_studio_hierarchy(studio, 0)
        assert result == ["Parent", "Child"]

    def test_three_level_hierarchy(self):
        """Three levels: root/middle/leaf ordering."""
        studio = {
            "id": "3",
            "name": "Leaf",
            "parent_studio": {
                "id": "2",
                "name": "Middle",
                "parent_studio": {
                    "id": "1",
                    "name": "Root",
                    "parent_studio": None,
                },
            },
        }
        result = _build_studio_hierarchy(studio, 0)
        assert result == ["Root", "Middle", "Leaf"]

    def test_circular_reference_terminates(self):
        """Circular reference: A -> B -> A should terminate without infinite loop."""
        studio_a = {"id": "1", "name": "A"}
        studio_b = {"id": "2", "name": "B", "parent_studio": studio_a}
        studio_a["parent_studio"] = studio_b
        result = _build_studio_hierarchy(studio_a, 0)
        # Should include both A and B but not loop
        assert "A" in result
        assert "B" in result
        assert len(result) == 2

    def test_max_depth_one(self):
        """max_depth=1: only immediate studio, no parent traversal."""
        studio = {
            "id": "2",
            "name": "Child",
            "parent_studio": {
                "id": "1",
                "name": "Parent",
                "parent_studio": None,
            },
        }
        result = _build_studio_hierarchy(studio, 1)
        assert result == ["Child"]

    def test_max_depth_two(self):
        """max_depth=2: stops at 2 levels even if more exist."""
        studio = {
            "id": "3",
            "name": "Leaf",
            "parent_studio": {
                "id": "2",
                "name": "Middle",
                "parent_studio": {
                    "id": "1",
                    "name": "Root",
                    "parent_studio": None,
                },
            },
        }
        result = _build_studio_hierarchy(studio, 2)
        # Collects Leaf (depth 1) and Middle (depth 2), stops before Root
        assert result == ["Middle", "Leaf"]

    def test_max_depth_zero_unlimited(self):
        """max_depth=0: unlimited traversal."""
        studio = {
            "id": "3",
            "name": "Leaf",
            "parent_studio": {
                "id": "2",
                "name": "Middle",
                "parent_studio": {
                    "id": "1",
                    "name": "Root",
                    "parent_studio": None,
                },
            },
        }
        result = _build_studio_hierarchy(studio, 0)
        assert result == ["Root", "Middle", "Leaf"]

    def test_empty_studio(self):
        """Empty/falsy studio returns empty list."""
        assert _build_studio_hierarchy({}, 0) == []
        assert _build_studio_hierarchy(None, 0) == []


# =============================================================================
# _extract_studio
# =============================================================================


class TestExtractStudio:
    """Tests for _extract_studio: extract studio template variables."""

    def test_no_studio_none(self, make_studio_config):
        """None studio returns all empty strings."""
        config = make_studio_config()
        result = _extract_studio(None, config)
        assert result["studio"] == ""
        assert result["parent_studio"] == ""
        assert result["studio_family"] == ""
        assert result["studio_hierarchy"] == ""

    def test_studio_no_parent(self, make_studio_config):
        """Studio with no parent: studio_family = studio name."""
        config = make_studio_config()
        studio = {"id": "1", "name": "Solo Studio", "parent_studio": None}
        result = _extract_studio(studio, config)
        assert result["studio"] == "Solo Studio"
        assert result["parent_studio"] == ""
        assert result["studio_family"] == "Solo Studio"
        assert result["studio_hierarchy"] == "Solo Studio"

    def test_studio_with_one_parent(self, make_studio_config):
        """Studio with one parent produces correct hierarchy."""
        config = make_studio_config()
        studio = {
            "id": "2",
            "name": "Child Studio",
            "parent_studio": {
                "id": "1",
                "name": "Parent Studio",
                "parent_studio": None,
            },
        }
        result = _extract_studio(studio, config)
        assert result["studio"] == "Child Studio"
        assert result["parent_studio"] == "Parent Studio"
        assert result["studio_family"] == "Parent Studio"
        assert result["studio_hierarchy"] == "Parent Studio/Child Studio"

    def test_three_level_hierarchy(self, make_studio_config):
        """Three-level hierarchy: studio_family is root."""
        config = make_studio_config()
        studio = {
            "id": "3",
            "name": "Leaf",
            "parent_studio": {
                "id": "2",
                "name": "Middle",
                "parent_studio": {
                    "id": "1",
                    "name": "Root",
                    "parent_studio": None,
                },
            },
        }
        result = _extract_studio(studio, config)
        assert result["studio"] == "Leaf"
        assert result["parent_studio"] == "Middle"
        assert result["studio_family"] == "Root"
        assert result["studio_hierarchy"] == "Root/Middle/Leaf"

    def test_squeeze_names_true(self, make_studio_config):
        """squeeze_names=True removes spaces from all studio variables."""
        config = make_studio_config(squeeze_names=True)
        studio = {
            "id": "2",
            "name": "Vixen Media",
            "parent_studio": {
                "id": "1",
                "name": "Parent Network",
                "parent_studio": None,
            },
        }
        result = _extract_studio(studio, config)
        assert result["studio"] == "VixenMedia"
        assert result["parent_studio"] == "ParentNetwork"
        assert result["studio_family"] == "ParentNetwork"
        assert result["studio_hierarchy"] == "ParentNetwork/VixenMedia"

    def test_squeeze_names_false(self, make_studio_config):
        """squeeze_names=False preserves spaces."""
        config = make_studio_config(squeeze_names=False)
        studio = {
            "id": "1",
            "name": "Vixen Media",
            "parent_studio": None,
        }
        result = _extract_studio(studio, config)
        assert result["studio"] == "Vixen Media"

    def test_max_hierarchy_depth(self, make_studio_config):
        """max_hierarchy_depth limits hierarchy traversal."""
        config = make_studio_config(max_hierarchy_depth=1)
        studio = {
            "id": "2",
            "name": "Child",
            "parent_studio": {
                "id": "1",
                "name": "Parent",
                "parent_studio": None,
            },
        }
        result = _extract_studio(studio, config)
        # Depth 1: only Child collected
        assert result["studio_hierarchy"] == "Child"
        assert result["studio_family"] == "Child"

    def test_all_values_are_strings(self, make_studio_config):
        """All returned values must be strings, never None."""
        config = make_studio_config()
        studio = {
            "id": "1",
            "name": "Test",
            "parent_studio": None,
        }
        result = _extract_studio(studio, config)
        for key, val in result.items():
            assert isinstance(val, str), f"{key}={val!r} is not str"

    def test_circular_reference_studio(self, make_studio_config):
        """Circular reference in studio hierarchy terminates safely."""
        config = make_studio_config()
        studio_a = {"id": "1", "name": "A"}
        studio_b = {"id": "2", "name": "B", "parent_studio": studio_a}
        studio_a["parent_studio"] = studio_b
        result = _extract_studio(studio_a, config)
        # Should not infinite loop, and produce valid strings
        assert isinstance(result["studio"], str)
        assert isinstance(result["studio_hierarchy"], str)
        assert result["studio"] == "A"


# =============================================================================
# TEMPLATE_VARIABLES constant
# =============================================================================


class TestTemplateVariables:
    """Tests for the TEMPLATE_VARIABLES constant."""

    def test_is_dict(self):
        """TEMPLATE_VARIABLES must be a dict."""
        assert isinstance(TEMPLATE_VARIABLES, dict)

    def test_has_25_keys(self):
        """TEMPLATE_VARIABLES must have exactly 25 keys."""
        assert len(TEMPLATE_VARIABLES) == 25

    def test_all_values_empty_string(self):
        """Every value in TEMPLATE_VARIABLES must be an empty string."""
        for key, value in TEMPLATE_VARIABLES.items():
            assert value == "", f"TEMPLATE_VARIABLES['{key}'] should be '' but is {value!r}"

    def test_expected_keys(self):
        """All 25 expected variable names must be present."""
        expected = {
            "title", "date", "year", "date_format", "rating",
            "performer", "stashid_performer",
            "studio", "parent_studio", "studio_family", "studio_hierarchy", "studio_code",
            "tags",
            "height", "resolution", "duration", "bitrate", "video_codec", "audio_codec",
            "oshash", "checksum",
            "movie_title", "movie_year", "movie_scene",
            "stashid_scene",
        }
        assert set(TEMPLATE_VARIABLES.keys()) == expected


# =============================================================================
# extract_metadata (orchestrator)
# =============================================================================


class TestExtractMetadata:
    """Integration tests for extract_metadata orchestrator."""

    def test_full_scene_all_keys_present(self, full_scene):
        """Full scene with default Config produces all 25 keys."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert set(result.keys()) == set(TEMPLATE_VARIABLES.keys())

    def test_full_scene_title(self, full_scene):
        """Full scene title extracted correctly."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["title"] == "Scene Title"

    def test_full_scene_date(self, full_scene):
        """Full scene date extracted correctly."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["date"] == "2024-01-15"

    def test_full_scene_year(self, full_scene):
        """Full scene year extracted from date."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["year"] == "2024"

    def test_full_scene_performer(self, full_scene):
        """Full scene performers extracted and joined."""
        config = Config()
        result = extract_metadata(full_scene, config)
        # Default sort is "id", default separator is " "
        # Performer IDs are "10" and "11" -> sorted by ID -> Alpha then Beta
        assert result["performer"] == "Performer Alpha Performer Beta"

    def test_full_scene_studio(self, full_scene):
        """Full scene studio name extracted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["studio"] == "Studio Name"

    def test_full_scene_parent_studio(self, full_scene):
        """Full scene parent_studio name extracted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["parent_studio"] == "Parent Studio"

    def test_full_scene_studio_family(self, full_scene):
        """Full scene studio_family is root of hierarchy."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["studio_family"] == "Parent Studio"

    def test_full_scene_oshash(self, full_scene):
        """Full scene oshash extracted from fingerprints."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["oshash"] == "abc123hash"

    def test_full_scene_movie_title(self, full_scene):
        """Full scene movie_title extracted from groups."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["movie_title"] == "Movie Title"

    def test_full_scene_height(self, full_scene):
        """Full scene height label extracted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["height"] == "1080p"

    def test_full_scene_resolution(self, full_scene):
        """Full scene resolution category extracted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["resolution"] == "HD"

    def test_full_scene_rating(self, full_scene):
        """Full scene rating formatted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["rating"] == "80"

    def test_full_scene_tags(self, full_scene):
        """Full scene tags joined with default separator."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["tags"] == "Tag One Tag Two Tag Three"

    def test_full_scene_studio_code(self, full_scene):
        """Full scene studio_code extracted from scene.code."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["studio_code"] == "ABC-123"

    def test_full_scene_stashid_scene(self, full_scene):
        """Full scene stashid_scene extracted."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["stashid_scene"] == "scene-uuid-123"

    def test_full_scene_checksum(self, full_scene):
        """Full scene checksum fingerprint not found (md5 only in fixture)."""
        config = Config()
        result = extract_metadata(full_scene, config)
        # Fixture has "md5" type, not "checksum" -- should be ""
        assert result["checksum"] == ""

    def test_full_scene_video_codec(self, full_scene):
        """Full scene video_codec extracted and uppercased."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["video_codec"] == "H264"

    def test_full_scene_audio_codec(self, full_scene):
        """Full scene audio_codec extracted and uppercased."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["audio_codec"] == "AAC"

    def test_bare_scene_all_keys_present(self, bare_scene):
        """Bare scene produces all 25 keys."""
        config = Config()
        result = extract_metadata(bare_scene, config)
        assert set(result.keys()) == set(TEMPLATE_VARIABLES.keys())

    def test_bare_scene_all_values_empty(self, bare_scene):
        """Bare scene produces empty string for every variable without exceptions."""
        config = Config()
        result = extract_metadata(bare_scene, config)
        for key, value in result.items():
            assert value == "", f"bare_scene result['{key}'] should be '' but is {value!r}"

    def test_type_safety_full_scene(self, full_scene):
        """Full scene: all values must be str type."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert all(isinstance(v, str) for v in result.values()), (
            f"Non-string values: {[(k, type(v)) for k, v in result.items() if not isinstance(v, str)]}"
        )

    def test_type_safety_bare_scene(self, bare_scene):
        """Bare scene: all values must be str type."""
        config = Config()
        result = extract_metadata(bare_scene, config)
        assert all(isinstance(v, str) for v in result.values()), (
            f"Non-string values: {[(k, type(v)) for k, v in result.items() if not isinstance(v, str)]}"
        )

    def test_prevent_title_duplicate_true(self):
        """When title == performer name and prevent_title_duplicate=True, performer is cleared."""
        scene = {
            "id": "1",
            "title": "Alice",
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [],
            "studio": None,
            "tags": [],
            "performers": [
                {"id": "1", "name": "Alice", "gender": "FEMALE", "favorite": False, "rating100": None, "stash_ids": []},
            ],
            "groups": [],
        }
        from dataclasses import replace
        config = Config()
        config = replace(config, performers=replace(config.performers, prevent_title_duplicate=True))
        result = extract_metadata(scene, config)
        assert result["performer"] == ""

    def test_prevent_title_duplicate_false(self):
        """When title == performer name but prevent_title_duplicate=False, performer is kept."""
        scene = {
            "id": "1",
            "title": "Alice",
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [],
            "studio": None,
            "tags": [],
            "performers": [
                {"id": "1", "name": "Alice", "gender": "FEMALE", "favorite": False, "rating100": None, "stash_ids": []},
            ],
            "groups": [],
        }
        from dataclasses import replace
        config = Config()
        config = replace(config, performers=replace(config.performers, prevent_title_duplicate=False))
        result = extract_metadata(scene, config)
        assert result["performer"] == "Alice"

    def test_variable_key_completeness_full(self, full_scene):
        """Full scene result keys exactly match TEMPLATE_VARIABLES keys."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert set(result.keys()) == set(TEMPLATE_VARIABLES.keys())

    def test_variable_key_completeness_bare(self, bare_scene):
        """Bare scene result keys exactly match TEMPLATE_VARIABLES keys."""
        config = Config()
        result = extract_metadata(bare_scene, config)
        assert set(result.keys()) == set(TEMPLATE_VARIABLES.keys())

    def test_duration_formatting_with_format(self):
        """Duration formatted with strftime when duration_format is configured."""
        scene = {
            "id": "1",
            "title": None,
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [
                {
                    "duration": 3661.0,  # 1 hour, 1 minute, 1 second
                    "width": 1920,
                    "height": 1080,
                }
            ],
            "studio": None,
            "tags": [],
            "performers": [],
            "groups": [],
        }
        from dataclasses import replace
        config = Config()
        config = replace(config, formatting=replace(config.formatting, duration_format="%H:%M:%S"))
        result = extract_metadata(scene, config)
        assert result["duration"] == "01:01:01"

    def test_duration_formatting_empty_format(self):
        """Duration remains raw seconds string when duration_format is empty."""
        scene = {
            "id": "1",
            "title": None,
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [
                {
                    "duration": 3661.0,
                    "width": 1920,
                    "height": 1080,
                }
            ],
            "studio": None,
            "tags": [],
            "performers": [],
            "groups": [],
        }
        config = Config()
        # default duration_format is ""
        result = extract_metadata(scene, config)
        assert result["duration"] == "3661.0"

    def test_config_performer_sort_delegation(self):
        """Changing config.performers.sort changes the performer output order."""
        scene = {
            "id": "1",
            "title": None,
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [],
            "studio": None,
            "tags": [],
            "performers": [
                {"id": "2", "name": "Bob", "gender": "MALE", "favorite": False, "rating100": 90, "stash_ids": []},
                {"id": "1", "name": "Alice", "gender": "FEMALE", "favorite": False, "rating100": 70, "stash_ids": []},
            ],
            "groups": [],
        }
        from dataclasses import replace

        # Sort by id: Alice (1) before Bob (2)
        config_id = Config()
        config_id = replace(config_id, performers=replace(config_id.performers, sort="id", limit=10))
        result_id = extract_metadata(scene, config_id)
        assert result_id["performer"] == "Alice Bob"

        # Sort by name: Alice before Bob (same result here since alphabetical)
        config_name = Config()
        config_name = replace(config_name, performers=replace(config_name.performers, sort="name", limit=10))
        result_name = extract_metadata(scene, config_name)
        assert result_name["performer"] == "Alice Bob"

        # Sort by rating: Bob (90) before Alice (70)
        config_rating = Config()
        config_rating = replace(config_rating, performers=replace(config_rating.performers, sort="rating", limit=10))
        result_rating = extract_metadata(scene, config_rating)
        assert result_rating["performer"] == "Bob Alice"

    def test_config_studio_squeeze_delegation(self):
        """Changing config.studios.squeeze_names changes studio output."""
        scene = {
            "id": "1",
            "title": None,
            "code": None,
            "date": None,
            "rating100": None,
            "organized": False,
            "stash_ids": [],
            "files": [],
            "studio": {
                "id": "1",
                "name": "Vixen Media",
                "parent_studio": None,
            },
            "tags": [],
            "performers": [],
            "groups": [],
        }
        from dataclasses import replace

        # squeeze_names=False: spaces preserved
        config_no_squeeze = Config()
        config_no_squeeze = replace(config_no_squeeze, studios=replace(config_no_squeeze.studios, squeeze_names=False))
        result_no = extract_metadata(scene, config_no_squeeze)
        assert result_no["studio"] == "Vixen Media"

        # squeeze_names=True: spaces removed
        config_squeeze = Config()
        config_squeeze = replace(config_squeeze, studios=replace(config_squeeze.studios, squeeze_names=True))
        result_yes = extract_metadata(scene, config_squeeze)
        assert result_yes["studio"] == "VixenMedia"

    def test_date_format_delegation(self, full_scene):
        """date_format from FormattingConfig applied correctly."""
        from dataclasses import replace
        config = Config()
        config = replace(config, formatting=replace(config.formatting, date_format="%d/%m/%Y"))
        result = extract_metadata(full_scene, config)
        assert result["date_format"] == "15/01/2024"

    def test_movie_scene_index(self, full_scene):
        """movie_scene shows 'scene N' for scenes with scene_index."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["movie_scene"] == "scene 3"

    def test_movie_year(self, full_scene):
        """movie_year extracted from group date."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["movie_year"] == "2024"

    def test_stashid_performer(self, full_scene):
        """stashid_performer joined from performer stash IDs."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["stashid_performer"] == "perf-uuid-1 perf-uuid-2"

    def test_studio_hierarchy(self, full_scene):
        """studio_hierarchy produced as '/'-joined hierarchy."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["studio_hierarchy"] == "Parent Studio/Studio Name"

    def test_bitrate(self, full_scene):
        """bitrate formatted as Mbps."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["bitrate"] == "5.0"

    def test_duration_raw(self, full_scene):
        """Duration is raw float string when no duration_format configured."""
        config = Config()
        result = extract_metadata(full_scene, config)
        assert result["duration"] == "1800.5"

    def test_no_extra_keys(self, full_scene):
        """No extra keys beyond TEMPLATE_VARIABLES are returned."""
        config = Config()
        result = extract_metadata(full_scene, config)
        extra = set(result.keys()) - set(TEMPLATE_VARIABLES.keys())
        assert not extra, f"Extra keys found: {extra}"

    def test_extract_metadata_is_public(self):
        """extract_metadata should be a public function (no underscore prefix)."""
        import metadata_extractor
        public_names = [n for n in dir(metadata_extractor) if not n.startswith("_")]
        assert "extract_metadata" in public_names

    def test_template_variables_is_public(self):
        """TEMPLATE_VARIABLES should be a public constant (no underscore prefix)."""
        import metadata_extractor
        public_names = [n for n in dir(metadata_extractor) if not n.startswith("_")]
        assert "TEMPLATE_VARIABLES" in public_names


# =============================================================================
# _invert_performer_names
# =============================================================================


class TestInvertPerformerNames:
    """Tests for _invert_performer_names: invert 'Last, First' to 'First Last'."""

    def test_invert_single_performer_comma_format(self):
        """'Doe, Jane' -> 'Jane Doe'. Standard Stash 'Last, First' convention."""
        from metadata_extractor import _invert_performer_names

        assert _invert_performer_names("Doe, Jane") == "Jane Doe"

    def test_invert_multiple_performers(self):
        """'Doe, Jane Smith, John' with space separator -> 'Jane Doe John Smith'."""
        from metadata_extractor import _invert_performer_names

        result = _invert_performer_names("Doe, Jane Smith, John", separator=" ")
        assert result == "Jane Doe John Smith"

    def test_invert_single_name_no_comma(self):
        """'Madonna' (no comma) is returned unchanged."""
        from metadata_extractor import _invert_performer_names

        assert _invert_performer_names("Madonna") == "Madonna"

    def test_invert_empty_string(self):
        """Empty string returns empty string."""
        from metadata_extractor import _invert_performer_names

        assert _invert_performer_names("") == ""

    def test_invert_custom_separator(self):
        """'Doe, Jane_Smith, John' with '_' separator -> 'Jane Doe_John Smith'."""
        from metadata_extractor import _invert_performer_names

        result = _invert_performer_names("Doe, Jane_Smith, John", separator="_")
        assert result == "Jane Doe_John Smith"
