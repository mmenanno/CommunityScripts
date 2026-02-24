"""Tests for the config_loader module.

Covers deep_merge, load_config, Config.from_dict, validate_config,
TagModifiers dataclass, tag_options validation,
DEFAULT_CONFIG_YAML round-trip, and default config generation.
All tests use tmp_path pytest fixture for temporary config files.
"""

import os
from unittest.mock import patch

import pytest
import yaml

from config_loader import (
    DEFAULT_CONFIG_YAML,
    DEFAULTS,
    Config,
    TagModifiers,
    deep_merge,
    load_config,
    validate_config,
)


# ---------------------------------------------------------------------------
# deep_merge tests
# ---------------------------------------------------------------------------


class TestDeepMerge:
    """Tests for the deep_merge() function."""

    def test_deep_merge_simple(self):
        """Override a single key in a flat dict, verify other keys preserved."""
        base = {"a": 1, "b": 2, "c": 3}
        override = {"b": 20}
        result = deep_merge(base, override)
        assert result == {"a": 1, "b": 20, "c": 3}

    def test_deep_merge_nested(self):
        """Override a nested key, verify sibling keys and other sections preserved."""
        base = {
            "text": {"lowercase": False, "titlecase": False, "space_char": " "},
            "general": {"debug": False},
        }
        override = {"text": {"lowercase": True}}
        result = deep_merge(base, override)
        assert result["text"]["lowercase"] is True
        assert result["text"]["titlecase"] is False
        assert result["text"]["space_char"] == " "
        assert result["general"]["debug"] is False

    def test_deep_merge_does_not_mutate_base(self):
        """Verify deep_merge returns a new dict and does not mutate the base."""
        base = {"a": {"b": 1, "c": [1, 2, 3]}}
        override = {"a": {"b": 10}}
        original_base = {"a": {"b": 1, "c": [1, 2, 3]}}
        result = deep_merge(base, override)

        # Base unchanged
        assert base == original_base
        # Result is a different object
        assert result is not base
        assert result["a"] is not base["a"]
        # Override applied
        assert result["a"]["b"] == 10


# ---------------------------------------------------------------------------
# load_config tests
# ---------------------------------------------------------------------------


class TestLoadConfig:
    """Tests for load_config() function."""

    def test_load_config_defaults(self, tmp_path):
        """Write empty dict config.yaml, verify Config has all default values."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("{}")
        config = load_config(str(tmp_path))
        assert config is not None
        assert config.filename.default == "$date $title"
        assert config.text.lowercase is False
        assert config.paths.max_length == 240
        assert config.performers.limit == 3
        assert config.performers.sort == "id"
        assert config.general.debug is False
        assert config.studios.max_hierarchy_depth == 0

    def test_load_config_user_overrides(self, tmp_path):
        """Write config with overrides, verify overrides applied and defaults preserved."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("text:\n  lowercase: true\n  titlecase: true\n")
        config = load_config(str(tmp_path))
        assert config is not None
        assert config.text.lowercase is True
        assert config.text.titlecase is True
        # Non-overridden defaults preserved
        assert config.text.space_char == " "
        assert config.text.remove_chars == ",#"

    def test_load_config_missing_generates_default(self, tmp_path):
        """Call load_config on dir with no config.yaml; verify returns None and generates file."""
        config_path = tmp_path / "config.yaml"
        assert not config_path.exists()

        with patch("config_loader.log") as mock_log:
            result = load_config(str(tmp_path))

        assert result is None
        assert config_path.exists()
        # Generated file should be valid YAML
        parsed = yaml.safe_load(config_path.read_text())
        assert isinstance(parsed, dict)
        mock_log.info.assert_called_once()

    def test_load_config_invalid_yaml(self, tmp_path):
        """Write invalid YAML, verify returns None and logs error."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("invalid: yaml: [broken")

        with patch("config_loader.log") as mock_log:
            result = load_config(str(tmp_path))

        assert result is None
        mock_log.error.assert_called_once()

    def test_load_config_unknown_top_level_key(self, tmp_path):
        """Write config with typo top-level key, verify returns None with error."""
        config_file = tmp_path / "config.yaml"
        yaml.dump({"perfomer": {"separator": "-"}}, config_file.open("w"))

        with patch("config_loader.log") as mock_log:
            result = load_config(str(tmp_path))

        assert result is None
        mock_log.error.assert_called()
        error_msg = mock_log.error.call_args[0][0]
        assert "Unknown config sections" in error_msg

    def test_load_config_unknown_nested_key(self, tmp_path):
        """Write config with typo nested key, verify returns None with error."""
        config_file = tmp_path / "config.yaml"
        yaml.dump({"text": {"lowrcase": True}}, config_file.open("w"))

        with patch("config_loader.log") as mock_log:
            result = load_config(str(tmp_path))

        assert result is None
        mock_log.error.assert_called()
        error_msg = mock_log.error.call_args[0][0]
        assert "lowrcase" in error_msg

    def test_load_config_empty_file(self, tmp_path):
        """Write empty string to config.yaml, verify Config with all defaults."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("")
        config = load_config(str(tmp_path))
        assert config is not None
        assert config.filename.default == "$date $title"
        assert config.paths.max_length == 240


# ---------------------------------------------------------------------------
# Config.from_dict tests
# ---------------------------------------------------------------------------


class TestConfigFromDict:
    """Tests for Config.from_dict() classmethod."""

    def test_config_from_dict(self):
        """Build Config from DEFAULTS dict, verify all sections instantiated."""
        config = Config.from_dict(DEFAULTS)
        assert isinstance(config.filename, type(config.filename))
        assert isinstance(config.text, type(config.text))
        assert isinstance(config.paths, type(config.paths))
        assert config.filename.default == "$date $title"
        assert config.text.prepositions == ["a", "an", "the", "of", "in", "on", "at", "for", "to", "and", "but", "or"]
        assert config.paths.length_reduction_order[0] == "$video_codec"
        assert config.exclusions.tags == []
        assert config.tag_options == {}


# ---------------------------------------------------------------------------
# DEFAULT_CONFIG_YAML tests
# ---------------------------------------------------------------------------


class TestDefaultConfigYaml:
    """Tests for the DEFAULT_CONFIG_YAML constant."""

    def test_default_config_yaml_roundtrip(self, tmp_path):
        """Parse DEFAULT_CONFIG_YAML, write to file, load_config should succeed."""
        parsed = yaml.safe_load(DEFAULT_CONFIG_YAML)
        assert isinstance(parsed, dict)

        # Write it as a config file and verify load_config works
        config_file = tmp_path / "config.yaml"
        config_file.write_text(DEFAULT_CONFIG_YAML)
        config = load_config(str(tmp_path))
        assert config is not None

    def test_default_config_yaml_not_empty(self):
        """DEFAULT_CONFIG_YAML must not be empty and must contain key sections."""
        assert len(DEFAULT_CONFIG_YAML) > 0
        assert "filename:" in DEFAULT_CONFIG_YAML
        assert "path:" in DEFAULT_CONFIG_YAML
        assert "text:" in DEFAULT_CONFIG_YAML
        assert "performers:" in DEFAULT_CONFIG_YAML
        assert "general:" in DEFAULT_CONFIG_YAML


# ---------------------------------------------------------------------------
# validate_config tests
# ---------------------------------------------------------------------------


class TestValidateConfig:
    """Tests for validate_config() function."""

    def test_validate_config_rejects_non_dict(self):
        """Pass a list to validate_config, verify error returned."""
        errors = validate_config([1, 2, 3])
        assert len(errors) == 1
        assert "mapping" in errors[0]

    def test_validate_config_accepts_valid(self):
        """Pass a dict with known keys only, verify no errors."""
        valid = {"text": {"lowercase": True}, "general": {"debug": True}}
        errors = validate_config(valid)
        assert errors == []

    def test_validate_config_rejects_unknown_tag_options_key(self):
        """Pass tag_options with an unknown modifier key, verify error returned."""
        user_config = {"tag_options": {"MyTag": {"cleantag": True}}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "unknown key 'cleantag'" in errors[0]
        assert "Valid keys: clean_tag, dry_run, inverse_performer" in errors[0]

    def test_validate_config_rejects_non_bool_tag_options_value(self):
        """Pass tag_options with non-bool value, verify error returned."""
        user_config = {"tag_options": {"MyTag": {"clean_tag": "yes"}}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "expected bool, got str" in errors[0]

    def test_validate_config_rejects_non_dict_tag_options_entry(self):
        """Pass tag_options with scalar value for tag, verify error returned."""
        user_config = {"tag_options": {"MyTag": "some_template"}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "expected dict" in errors[0]


# ---------------------------------------------------------------------------
# TagModifiers dataclass tests
# ---------------------------------------------------------------------------


class TestTagModifiers:
    """Tests for the TagModifiers dataclass."""

    def test_tag_modifiers_defaults(self):
        """TagModifiers() has all fields False by default."""
        mods = TagModifiers()
        assert mods.clean_tag is False
        assert mods.inverse_performer is False
        assert mods.dry_run is False

    def test_tag_modifiers_with_values(self):
        """TagModifiers(clean_tag=True) sets only clean_tag, others stay False."""
        mods = TagModifiers(clean_tag=True)
        assert mods.clean_tag is True
        assert mods.inverse_performer is False
        assert mods.dry_run is False


# ---------------------------------------------------------------------------
# validate_tag_options tests
# ---------------------------------------------------------------------------


class TestValidateTagOptions:
    """Tests for tag_options schema validation within validate_config."""

    def test_valid_tag_options_all_modifiers(self):
        """tag_options with all three booleans set passes validation."""
        user_config = {
            "tag_options": {
                "!1. JAV": {
                    "clean_tag": True,
                    "inverse_performer": True,
                    "dry_run": False,
                }
            }
        }
        errors = validate_config(user_config)
        assert errors == []

    def test_valid_tag_options_partial_modifiers(self):
        """tag_options with only clean_tag set passes validation."""
        user_config = {"tag_options": {"SomeTag": {"clean_tag": True}}}
        errors = validate_config(user_config)
        assert errors == []

    def test_valid_tag_options_empty_entry(self):
        """tag_options with empty dict entry passes validation (no errors)."""
        user_config = {"tag_options": {"SomeTag": {}}}
        errors = validate_config(user_config)
        assert errors == []

    def test_invalid_unknown_key(self):
        """tag_options with unknown key returns error with key name and valid keys list."""
        user_config = {"tag_options": {"Tag": {"cleantag": True}}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "unknown key 'cleantag'" in errors[0]
        assert "Valid keys: clean_tag, dry_run, inverse_performer" in errors[0]

    def test_invalid_non_bool_value(self):
        """tag_options with non-bool value returns error with type info."""
        user_config = {"tag_options": {"Tag": {"clean_tag": "yes"}}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "expected bool, got str" in errors[0]

    def test_invalid_non_dict_entry(self):
        """tag_options with scalar value for tag entry returns error."""
        user_config = {"tag_options": {"Tag": "some_template"}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "expected dict" in errors[0]

    def test_invalid_list_entry(self):
        """tag_options with list value for tag entry returns error."""
        user_config = {"tag_options": {"Tag": [1, 2]}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "expected dict" in errors[0]

    def test_multiple_errors_collected(self):
        """tag_options with multiple invalid tags collects all errors."""
        user_config = {
            "tag_options": {
                "Tag1": {"cleantag": True},
                "Tag2": {"clean_tag": "yes"},
            }
        }
        errors = validate_config(user_config)
        assert len(errors) == 2

    def test_tag_name_in_error_message(self):
        """Error message includes the tag name in path notation."""
        user_config = {"tag_options": {"!1. JAV": {"cleantag": True}}}
        errors = validate_config(user_config)
        assert len(errors) == 1
        assert "tag_options['!1. JAV']" in errors[0]


# ---------------------------------------------------------------------------
# tag_options integration tests (in TestLoadConfig additions)
# ---------------------------------------------------------------------------


class TestLoadConfigTagOptions:
    """Integration tests for tag_options through load_config."""

    def test_load_config_tag_options_creates_tag_modifiers(self, tmp_path):
        """Config with valid tag_options creates TagModifiers instances."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "filename:\n"
            "  tag_templates:\n"
            "    MyTag: '$title'\n"
            "tag_options:\n"
            "  MyTag:\n"
            "    clean_tag: true\n"
        )
        config = load_config(str(tmp_path))
        assert config is not None
        assert "MyTag" in config.tag_options
        assert isinstance(config.tag_options["MyTag"], TagModifiers)
        assert config.tag_options["MyTag"].clean_tag is True
        assert config.tag_options["MyTag"].inverse_performer is False

    def test_load_config_tag_options_invalid_rejects(self, tmp_path):
        """Config with invalid tag_options key returns None."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "tag_options:\n"
            "  MyTag:\n"
            "    badkey: true\n"
        )
        with patch("config_loader.log"):
            result = load_config(str(tmp_path))
        assert result is None

    def test_load_config_existing_behavior_unchanged(self, tmp_path):
        """Config with no tag_options section loads with empty tag_options dict."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text("text:\n  lowercase: true\n")
        config = load_config(str(tmp_path))
        assert config is not None
        assert config.tag_options == {}

    def test_load_config_orphan_tag_options_warns(self, tmp_path):
        """tag_options for a tag with no matching template logs a warning."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "tag_options:\n"
            "  OrphanTag:\n"
            "    clean_tag: true\n"
        )
        with patch("config_loader.log") as mock_log:
            config = load_config(str(tmp_path))
        assert config is not None
        # Verify warning was called with the orphan tag name
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("OrphanTag" in w for w in warning_calls)

    def test_load_config_empty_tag_options_entry_warns(self, tmp_path):
        """tag_options with empty dict entry logs a warning about no effect."""
        config_file = tmp_path / "config.yaml"
        config_file.write_text(
            "filename:\n"
            "  tag_templates:\n"
            "    SomeTag: '$title'\n"
            "tag_options:\n"
            "  SomeTag: {}\n"
        )
        with patch("config_loader.log") as mock_log:
            config = load_config(str(tmp_path))
        assert config is not None
        warning_calls = [str(c) for c in mock_log.warning.call_args_list]
        assert any("SomeTag" in w for w in warning_calls)
