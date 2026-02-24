"""Tests for the template_engine module.

Covers three core rendering functions: substitute_variables, expand_groups,
and render_template. Tests verify variable substitution, conditional
group expansion, two-pass rendering order, and prefix collision prevention.

Also covers template selection: select_filename_template and
select_path_template with tag > studio > path-match > default priority chain.
"""

import pytest


# =============================================================================
# substitute_variables tests
# =============================================================================


class TestSubstituteVariables:
    """Tests for substitute_variables() - $variable placeholder replacement."""

    def test_single_variable_substitution(self):
        """Single $variable is replaced with its value."""
        from template_engine import substitute_variables

        result = substitute_variables("$title", {"title": "Hello"})
        assert result == "Hello"

    def test_multiple_variables(self):
        """Multiple $variables are all replaced correctly."""
        from template_engine import substitute_variables

        result = substitute_variables(
            "$date $title", {"date": "2024-01-01", "title": "Movie"}
        )
        assert result == "2024-01-01 Movie"

    def test_unknown_variable_maps_to_empty(self):
        """Unknown $variable is replaced with empty string, not left as literal."""
        from template_engine import substitute_variables

        result = substitute_variables("$unknown", {})
        assert result == ""

    def test_no_variables_unchanged(self):
        """Text without $variables passes through unchanged."""
        from template_engine import substitute_variables

        result = substitute_variables("plain text", {"title": "Hello"})
        assert result == "plain text"

    def test_prefix_collision_studio(self):
        """$studio and $studio_family resolve independently without prefix collision."""
        from template_engine import substitute_variables

        result = substitute_variables(
            "$studio - $studio_family",
            {"studio": "Brazzers", "studio_family": "MindGeek"},
        )
        assert result == "Brazzers - MindGeek"

    def test_many_variables(self):
        """Template with 5+ variables all resolve correctly."""
        from template_engine import substitute_variables

        variables = {
            "title": "Movie",
            "date": "2024-01-01",
            "studio": "Studio",
            "performer": "Jane",
            "resolution": "1080p",
            "rating": "5",
        }
        template = "$date $performer - $title [$studio] $resolution $rating"
        result = substitute_variables(template, variables)
        assert result == "2024-01-01 Jane - Movie [Studio] 1080p 5"

    def test_empty_string_template(self):
        """Empty template returns empty string."""
        from template_engine import substitute_variables

        result = substitute_variables("", {"title": "Hello"})
        assert result == ""

    def test_variable_at_boundaries(self):
        """Variables adjacent to non-identifier chars resolve correctly."""
        from template_engine import substitute_variables

        # Period terminates the variable name
        result = substitute_variables("$title.", {"title": "Movie"})
        assert result == "Movie."

        # Square brackets are not part of the variable name
        result = substitute_variables("[$studio]", {"studio": "Brazzers"})
        assert result == "[Brazzers]"


# =============================================================================
# expand_groups tests
# =============================================================================


class TestExpandGroups:
    """Tests for expand_groups() - {$var text} conditional group expansion."""

    def test_group_with_value_renders(self):
        """Group with all variables present renders with substitution and braces stripped."""
        from template_engine import expand_groups

        result = expand_groups(
            "{$date - }$title",
            {"date": "2024-01-01", "title": "Title"},
        )
        assert result == "2024-01-01 - $title"

    def test_group_with_empty_var_removed(self):
        """Group is completely removed when its variable is empty."""
        from template_engine import expand_groups

        result = expand_groups(
            "{$date - }$title",
            {"date": "", "title": "Title"},
        )
        # Group removed entirely, remaining $title NOT substituted by expand_groups
        assert result == "$title"

    def test_multiple_groups(self):
        """Multiple groups are processed independently."""
        from template_engine import expand_groups

        result = expand_groups(
            "{$date - }{$studio: }$title",
            {"date": "", "studio": "X", "title": "Movie"},
        )
        # First group removed (date empty), second group rendered
        assert result == "X: $title"

    def test_group_all_vars_present(self):
        """Group with multiple variables all present renders with substitution."""
        from template_engine import expand_groups

        result = expand_groups(
            "{$performer - $title}",
            {"performer": "Jane", "title": "Movie"},
        )
        assert result == "Jane - Movie"

    def test_group_any_var_empty_removes(self):
        """Group is removed when ANY variable inside it is empty."""
        from template_engine import expand_groups

        result = expand_groups(
            "{$performer - $title}",
            {"performer": "", "title": "Movie"},
        )
        assert result == ""

    def test_no_groups_unchanged(self):
        """Template without groups passes through unchanged."""
        from template_engine import expand_groups

        result = expand_groups(
            "$date $title",
            {"date": "2024-01-01", "title": "Movie"},
        )
        assert result == "$date $title"

    def test_empty_group(self):
        """Empty group {} is removed."""
        from template_engine import expand_groups

        result = expand_groups("{}", {"title": "Movie"})
        assert result == ""


# =============================================================================
# render_template tests
# =============================================================================


class TestRenderTemplate:
    """Tests for render_template() - two-pass rendering: groups first, then substitution."""

    def test_two_pass_order(self):
        """Groups are expanded first, then remaining variables are substituted."""
        from template_engine import render_template

        result = render_template(
            "{$date - }$title",
            {"date": "", "title": "Hello"},
        )
        # Pass 1 (expand_groups): removes {$date - } -> "$title"
        # Pass 2 (substitute_variables): replaces $title -> "Hello"
        assert result == "Hello"

    def test_delimiter_leak_prevention(self):
        """Two-pass rendering prevents delimiter leaking (Issue #101 fix)."""
        from template_engine import render_template

        result = render_template(
            "{$date - }$title",
            {"date": "", "title": "Hello"},
        )
        # The " - " separator must NOT appear in output when $date is empty
        assert " - " not in result

    def test_full_render_with_groups_and_vars(self):
        """Full render with groups and variables, all values present."""
        from template_engine import render_template

        result = render_template(
            "[$studio] {$date - }$title",
            {"studio": "Brazzers", "date": "2024-01-01", "title": "Movie"},
        )
        assert result == "[Brazzers] 2024-01-01 - Movie"

    def test_full_render_mixed_empty(self):
        """Full render with some empty variables removes their groups."""
        from template_engine import render_template

        result = render_template(
            "[$studio] {$date - }$title",
            {"studio": "Brazzers", "date": "", "title": "Movie"},
        )
        assert result == "[Brazzers] Movie"

    def test_render_empty_template(self):
        """Empty template returns empty string."""
        from template_engine import render_template

        result = render_template("", {"title": "Hello"})
        assert result == ""

    def test_render_no_vars_plain_text(self):
        """Plain text without variables or groups returns unchanged."""
        from template_engine import render_template

        result = render_template("plain text", {})
        assert result == "plain text"


# =============================================================================
# TestSelectFilenameTemplate -- filename priority chain
# =============================================================================


class TestSelectFilenameTemplate:
    """Test select_filename_template: tag > studio > default priority."""

    def test_tag_match_wins_over_studio(self, make_filename_config):
        """When both tag and studio match, tag template takes priority."""
        from template_engine import select_filename_template

        config = make_filename_config(
            tag_templates={"JAV": "$title"},
            studio_templates={"Deeper": "[$studio] $title"},
        )
        result = select_filename_template(["JAV"], "Deeper", config)
        assert result == "$title"

    def test_studio_match_when_no_tag(self, make_filename_config):
        """When no tag matches but studio does, studio template is returned."""
        from template_engine import select_filename_template

        config = make_filename_config(
            tag_templates={"JAV": "$title"},
            studio_templates={"Deeper": "[$studio] $title"},
        )
        result = select_filename_template(["HD"], "Deeper", config)
        assert result == "[$studio] $title"

    def test_default_when_no_match_and_use_default_true(self, make_filename_config):
        """When nothing matches and use_default is True, return default template."""
        from template_engine import select_filename_template

        config = make_filename_config(
            use_default=True,
            default="$date $title",
        )
        result = select_filename_template([], "", config)
        assert result == "$date $title"

    def test_none_when_no_match_and_use_default_false(self, make_filename_config):
        """When nothing matches and use_default is False, return None."""
        from template_engine import select_filename_template

        config = make_filename_config(
            use_default=False,
        )
        result = select_filename_template([], "", config)
        assert result is None

    def test_first_matching_tag_wins(self, make_filename_config):
        """When multiple tags match, the first one in scene_tags list wins."""
        from template_engine import select_filename_template

        config = make_filename_config(
            tag_templates={
                "JAV": "$title",
                "HD": "$date $title",
            },
        )
        result = select_filename_template(["JAV", "HD"], "SomeStudio", config)
        assert result == "$title"

    def test_studio_empty_string_skipped(self, make_filename_config):
        """Empty studio string should not match even if empty key exists in templates."""
        from template_engine import select_filename_template

        config = make_filename_config(
            studio_templates={"": "bad template"},
            use_default=True,
            default="$date $title",
        )
        result = select_filename_template([], "", config)
        # Should skip empty studio and fall through to default
        assert result == "$date $title"

    def test_no_templates_configured(self, make_filename_config):
        """Empty config with use_default=False returns None."""
        from template_engine import select_filename_template

        config = make_filename_config(use_default=False)
        result = select_filename_template([], "", config)
        assert result is None


# =============================================================================
# TestSelectPathTemplate -- path priority chain
# =============================================================================


class TestSelectPathTemplate:
    """Test select_path_template: tag > studio > path-match > default priority."""

    def test_tag_highest_priority(self, make_path_config):
        """Tag template wins over studio, path-match, and default."""
        from template_engine import select_path_template

        config = make_path_config(
            tag_templates={"JAV": "/jav/$performer"},
            studio_templates={"Deeper": "/studios/$studio"},
            path_templates={"/unsorted": "/sorted/$performer"},
            use_default=True,
            default="^*/$performer",
        )
        result = select_path_template(
            ["JAV"], "Deeper", "/stash/videos/unsorted/scene.mp4", config
        )
        assert result == "/jav/$performer"

    def test_studio_over_path_match(self, make_path_config):
        """Studio template wins over path-match and default when no tag matches."""
        from template_engine import select_path_template

        config = make_path_config(
            studio_templates={"Deeper": "/studios/$studio"},
            path_templates={"/unsorted": "/sorted/$performer"},
            use_default=True,
            default="^*/$performer",
        )
        result = select_path_template(
            ["HD"], "Deeper", "/stash/videos/unsorted/scene.mp4", config
        )
        assert result == "/studios/$studio"

    def test_path_match_over_default(self, make_path_config):
        """Path-match template wins over default when no tag/studio matches."""
        from template_engine import select_path_template

        config = make_path_config(
            path_templates={"/unsorted": "/sorted/$performer"},
            use_default=True,
            default="^*/$performer",
        )
        result = select_path_template(
            [], "", "/stash/videos/unsorted/scene.mp4", config
        )
        assert result == "/sorted/$performer"

    def test_path_match_substring(self, make_path_config):
        """Path matching uses substring 'in' operator for backward compatibility."""
        from template_engine import select_path_template

        config = make_path_config(
            path_templates={"/unsorted": "/sorted/$performer"},
        )
        result = select_path_template(
            [], "", "/stash/videos/unsorted/scene.mp4", config
        )
        assert result == "/sorted/$performer"

    def test_default_when_nothing_matches(self, make_path_config):
        """Default template returned when use_default=True and nothing else matches."""
        from template_engine import select_path_template

        config = make_path_config(
            use_default=True,
            default="^*/$performer",
        )
        result = select_path_template([], "", "/stash/videos/scene.mp4", config)
        assert result == "^*/$performer"

    def test_none_when_nothing_and_no_default(self, make_path_config):
        """Returns None when nothing matches and use_default is False."""
        from template_engine import select_path_template

        config = make_path_config(use_default=False)
        result = select_path_template([], "", "/stash/videos/scene.mp4", config)
        assert result is None

    def test_path_no_false_positive(self, make_path_config):
        """Path matching with 'in' does substring match -- /stash matches /stash-archive.

        This is intentional for backward compatibility with renamerOnUpdate configs.
        The 'in' operator performs substring matching, not path-prefix matching.
        """
        from template_engine import select_path_template

        config = make_path_config(
            path_templates={"/stash": "/organized/$performer"},
        )
        # /stash IS a substring of /stash-archive/videos/scene.mp4
        result = select_path_template(
            [], "", "/stash-archive/videos/scene.mp4", config
        )
        assert result == "/organized/$performer"
