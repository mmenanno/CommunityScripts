"""Tests for the text_processor module.

Covers all eight pure text transformation functions plus the process_text
pipeline orchestrator: normalize_unicode, replace_words, remove_chars,
remove_prepositions, apply_titlecase, transliterate_ascii,
sanitize_filename, replace_spaces, and process_text.
"""

from unittest.mock import patch

import pytest


# =============================================================================
# normalize_unicode tests
# =============================================================================


class TestNormalizeUnicode:
    """Tests for normalize_unicode() - NFC Unicode normalization."""

    def test_nfd_to_nfc(self):
        """NFD input (decomposed) is normalized to NFC (composed)."""
        from text_processor import normalize_unicode

        # "Chloe" with combining acute accent (NFD: e + combining accent)
        nfd_input = "Chloe\u0301"
        result = normalize_unicode(nfd_input)
        assert result == "Chlo\u00e9"
        assert len(result) == 5  # NFC is 5 chars, NFD was 6

    def test_already_nfc_unchanged(self):
        """Already-NFC text passes through unchanged."""
        from text_processor import normalize_unicode

        nfc_input = "Chlo\u00e9"
        result = normalize_unicode(nfc_input)
        assert result == nfc_input

    def test_empty_string(self):
        """Empty string returns empty string."""
        from text_processor import normalize_unicode

        assert normalize_unicode("") == ""

    def test_ascii_only_unchanged(self):
        """ASCII-only text is unmodified."""
        from text_processor import normalize_unicode

        assert normalize_unicode("hello world") == "hello world"


# =============================================================================
# replace_words tests
# =============================================================================


class TestReplaceWords:
    """Tests for replace_words() - three-mode word replacement."""

    def test_whole_word_mode(self):
        """Whole-word mode replaces full words only."""
        from text_processor import replace_words

        result = replace_words("hello world", {"hello": ["hi", "word"]})
        assert result == "hi world"

    def test_whole_word_no_partial_match(self):
        """Whole-word mode does NOT match partial words."""
        from text_processor import replace_words

        result = replace_words("helloworld", {"hello": ["hi", "word"]})
        assert result == "helloworld"

    def test_regex_mode(self):
        """Regex mode applies raw regex pattern."""
        from text_processor import replace_words

        result = replace_words("scene 123", {"\\d+": ["NUM", "regex"]})
        assert result == "scene NUM"

    def test_any_substring_mode(self):
        """Any-substring mode matches anywhere in text."""
        from text_processor import replace_words

        result = replace_words("foo bar", {"oo": ["00", "any"]})
        assert result == "f00 bar"

    def test_legacy_string_format(self):
        """Legacy Dict[str, str] format treats value as whole-word replacement."""
        from text_processor import replace_words

        result = replace_words("hello world", {"hello": "hi"})
        assert result == "hi world"

    def test_sequential_chaining(self):
        """Rule 1 output feeds into rule 2 (sequential chaining)."""
        from text_processor import replace_words

        # First rule: hello -> hi (word mode)
        # Second rule: hi -> hey (word mode)
        replacer = {"hello": ["hi", "word"], "hi": ["hey", "word"]}
        result = replace_words("hello world", replacer)
        assert result == "hey world"

    def test_case_insensitive_matching(self):
        """Matching is case-insensitive."""
        from text_processor import replace_words

        result = replace_words("Hello World", {"hello": ["hi", "word"]})
        assert result == "hi World"

    def test_empty_word_replacer(self):
        """Empty word_replacer dict returns text unchanged."""
        from text_processor import replace_words

        assert replace_words("hello world", {}) == "hello world"


# =============================================================================
# remove_chars tests
# =============================================================================


class TestRemoveChars:
    """Tests for remove_chars() - character removal."""

    def test_removes_specified_chars(self):
        """Specified characters are removed from text."""
        from text_processor import remove_chars

        result = remove_chars("hello, world #1", ",#")
        assert result == "hello world 1"

    def test_empty_chars_string(self):
        """Empty remove_chars string returns text unchanged."""
        from text_processor import remove_chars

        assert remove_chars("hello, world", "") == "hello, world"

    def test_empty_input_text(self):
        """Empty input text returns empty string."""
        from text_processor import remove_chars

        assert remove_chars("", ",#") == ""


# =============================================================================
# remove_prepositions tests
# =============================================================================


class TestRemovePrepositions:
    """Tests for remove_prepositions() - preposition removal with word boundaries."""

    def test_removes_from_all_positions(self):
        """Removes prepositions from all positions including first word."""
        from text_processor import remove_prepositions

        result = remove_prepositions("The Walking Dead", ["the"])
        assert result == "Walking Dead"

    def test_preserves_words_containing_preposition(self):
        """Does NOT match inside words: 'theater' preserved when removing 'the'."""
        from text_processor import remove_prepositions

        result = remove_prepositions("the theater", ["the"])
        assert result == "theater"

    def test_case_insensitive(self):
        """Matching is case-insensitive."""
        from text_processor import remove_prepositions

        result = remove_prepositions("THE Walking Dead", ["the"])
        assert result == "Walking Dead"

    def test_multiple_prepositions(self):
        """Multiple prepositions are removed."""
        from text_processor import remove_prepositions

        result = remove_prepositions(
            "A Day in the Life", ["a", "in", "the"]
        )
        assert result == "Day Life"

    def test_cleans_up_multiple_spaces(self):
        """Multiple spaces after removal are collapsed."""
        from text_processor import remove_prepositions

        result = remove_prepositions("The  Walking  Dead", ["the"])
        # After removing "The" and collapsing whitespace
        assert "  " not in result
        assert result == "Walking Dead"

    def test_empty_prepositions_list(self):
        """Empty prepositions list returns text unchanged."""
        from text_processor import remove_prepositions

        assert remove_prepositions("The Walking Dead", []) == "The Walking Dead"


# =============================================================================
# apply_titlecase tests
# =============================================================================


class TestApplyTitlecase:
    """Tests for apply_titlecase() - custom titlecase preserving acronyms/caps."""

    def test_all_lowercase(self):
        """All-lowercase words get first letter capitalized."""
        from text_processor import apply_titlecase

        assert apply_titlecase("hello world") == "Hello World"

    def test_acronym_preservation(self):
        """All-caps words (2+ chars) are preserved as acronyms."""
        from text_processor import apply_titlecase

        assert apply_titlecase("BBC news report") == "BBC News Report"

    def test_mixed_case_preservation(self):
        """Mixed-case words are preserved as-is."""
        from text_processor import apply_titlecase

        assert apply_titlecase("McDonald is great") == "McDonald Is Great"

    def test_first_word_always_capitalized(self):
        """First word is always capitalized even if single char."""
        from text_processor import apply_titlecase

        assert apply_titlecase("a new day") == "A New Day"

    def test_contraction_handling(self):
        """Contractions are handled correctly."""
        from text_processor import apply_titlecase

        assert apply_titlecase("don't stop") == "Don't Stop"

    def test_already_correct_casing(self):
        """Already correct casing is preserved."""
        from text_processor import apply_titlecase

        assert apply_titlecase("HDTV rip") == "HDTV Rip"

    def test_empty_string(self):
        """Empty string returns empty string."""
        from text_processor import apply_titlecase

        assert apply_titlecase("") == ""

    def test_single_word(self):
        """Single word is capitalized."""
        from text_processor import apply_titlecase

        assert apply_titlecase("hello") == "Hello"

    def test_alphanumeric_words(self):
        """Alphanumeric words are capitalized (Claude's discretion)."""
        from text_processor import apply_titlecase

        assert apply_titlecase("h264 codec") == "H264 Codec"


# =============================================================================
# transliterate_ascii tests
# =============================================================================


class TestTransliterateAscii:
    """Tests for transliterate_ascii() - ASCII transliteration via Unidecode."""

    def test_accented_characters(self):
        """Accented characters are transliterated to ASCII."""
        from text_processor import transliterate_ascii

        assert transliterate_ascii("Chlo\u00e9") == "Chloe"

    def test_german_characters(self):
        """German umlauts are transliterated."""
        from text_processor import transliterate_ascii

        assert transliterate_ascii("\u00fcber") == "uber"

    def test_ascii_input_unchanged(self):
        """ASCII input passes through unchanged."""
        from text_processor import transliterate_ascii

        assert transliterate_ascii("hello world") == "hello world"

    def test_empty_string(self):
        """Empty string returns empty string."""
        from text_processor import transliterate_ascii

        assert transliterate_ascii("") == ""

    def test_import_error_fallback(self):
        """When Unidecode is not installed, falls back to stripping non-ASCII."""
        import importlib
        import text_processor

        with patch.dict("sys.modules", {"unidecode": None}):
            # Force reimport to trigger the ImportError path
            # We need to test the fallback within the function
            # Since the function does a local import, we mock it
            with patch("builtins.__import__", side_effect=_mock_import_no_unidecode):
                result = text_processor.transliterate_ascii("Chlo\u00e9")
                # Fallback strips non-ASCII: "Chlo\u00e9" -> "Chlo"
                assert result == "Chlo"


def _mock_import_no_unidecode(name, *args, **kwargs):
    """Mock import that raises ImportError for unidecode."""
    if name == "unidecode":
        raise ImportError("No module named 'unidecode'")
    return original_import(name, *args, **kwargs)


import builtins

original_import = builtins.__import__


# =============================================================================
# sanitize_filename tests
# =============================================================================


class TestSanitizeFilename:
    """Tests for sanitize_filename() - OS-illegal chars and Windows reserved names."""

    def test_illegal_char_replaced_with_separator(self):
        """Colon (illegal char) is replaced with separator, consecutive collapsed."""
        from text_processor import sanitize_filename

        result = sanitize_filename("Scene: The Title", " ")
        assert result == "Scene The Title"

    def test_all_os_illegal_chars_handled(self):
        r"""All OS-illegal chars \\/:*?\"<>| are replaced."""
        from text_processor import sanitize_filename

        result = sanitize_filename('A\\B/C:D*E?F"G<H>I|J', "-")
        # Each illegal char replaced with "-", consecutive collapsed
        assert "\\" not in result
        assert "/" not in result
        assert ":" not in result
        assert "*" not in result
        assert "?" not in result
        assert '"' not in result
        assert "<" not in result
        assert ">" not in result
        assert "|" not in result

    def test_control_chars_replaced(self):
        """Control characters (\\x00-\\x1f) are replaced."""
        from text_processor import sanitize_filename

        result = sanitize_filename("hello\x00world\x1f", "-")
        assert "\x00" not in result
        assert "\x1f" not in result

    def test_separator_collapsing(self):
        """Multiple consecutive separators are collapsed to one."""
        from text_processor import sanitize_filename

        # Each colon replaced with "-", then "---" collapsed to "-"
        result = sanitize_filename("A::B::C", "-")
        assert result == "A-B-C"

    def test_leading_trailing_separator_stripped(self):
        """Leading and trailing separators are stripped from output."""
        from text_processor import sanitize_filename

        # Leading colon -> leading separator -> stripped
        result = sanitize_filename(":hello:", "-")
        assert result == "hello"

    def test_leading_trailing_dots_stripped(self):
        """Leading and trailing dots are stripped."""
        from text_processor import sanitize_filename

        result = sanitize_filename("..hidden", " ")
        assert result == "hidden"

    def test_windows_reserved_name_con(self):
        """Windows reserved name CON is prefixed with underscore."""
        from text_processor import sanitize_filename

        result = sanitize_filename("CON", " ")
        assert result == "_CON"

    def test_windows_reserved_name_with_extension(self):
        """Reserved name with extension: stem is detected and prefixed."""
        from text_processor import sanitize_filename

        result = sanitize_filename("CON.mp4", " ")
        assert result == "_CON.mp4"

    def test_windows_reserved_name_case_insensitive(self):
        """Reserved name detection is case-insensitive."""
        from text_processor import sanitize_filename

        assert sanitize_filename("con", " ").startswith("_")
        assert sanitize_filename("Con", " ").startswith("_")
        assert sanitize_filename("CON", " ").startswith("_")

    def test_full_reserved_name_list(self):
        """All Windows reserved names are detected."""
        from text_processor import sanitize_filename

        reserved = [
            "CON", "PRN", "AUX", "NUL",
            "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
            "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
        ]
        for name in reserved:
            result = sanitize_filename(name, " ")
            assert result == f"_{name}", f"Expected '_{name}', got '{result}'"

    def test_non_reserved_name_passes_through(self):
        """Non-reserved names like CONCERT are not prefixed."""
        from text_processor import sanitize_filename

        result = sanitize_filename("CONCERT", " ")
        assert result == "CONCERT"

    def test_empty_separator_removes_chars(self):
        """When separator is empty string, illegal chars are removed entirely."""
        from text_processor import sanitize_filename

        result = sanitize_filename("A:B", "")
        assert result == "AB"

    def test_clean_text_passes_through(self):
        """Already-clean text passes through unchanged."""
        from text_processor import sanitize_filename

        result = sanitize_filename("Clean Title", " ")
        assert result == "Clean Title"


# =============================================================================
# replace_spaces tests
# =============================================================================


class TestReplaceSpaces:
    """Tests for replace_spaces() - space replacement with configured separator."""

    def test_basic_replacement(self):
        """Spaces are replaced with the configured separator."""
        from text_processor import replace_spaces

        result = replace_spaces("hello world", ".")
        assert result == "hello.world"

    def test_multiple_spaces_collapsed(self):
        """Multiple consecutive spaces are collapsed to a single separator."""
        from text_processor import replace_spaces

        result = replace_spaces("hello  world", ".")
        assert result == "hello.world"

    def test_space_separator_noop(self):
        """Space separator is effectively a no-op (collapses multiple spaces)."""
        from text_processor import replace_spaces

        result = replace_spaces("hello world", " ")
        assert result == "hello world"

    def test_underscore_separator(self):
        """Underscore separator works correctly."""
        from text_processor import replace_spaces

        result = replace_spaces("hello world", "_")
        assert result == "hello_world"

    def test_empty_string_input(self):
        """Empty string input returns empty string."""
        from text_processor import replace_spaces

        result = replace_spaces("", ".")
        assert result == ""


# =============================================================================
# process_text pipeline orchestrator tests
# =============================================================================


class TestProcessTextOrdering:
    """Tests for process_text() - strict pipeline ordering verification."""

    def test_empty_string_returns_empty(self, default_text_config):
        """Empty string input returns empty string."""
        from text_processor import process_text

        result = process_text("", default_text_config)
        assert result == ""

    def test_nfc_normalization_happens_first(self, make_text_config):
        """NFC normalization runs first: NFD + titlecase produces correct NFC output."""
        from text_processor import process_text

        config = make_text_config(titlecase=True)
        # NFD "Chloe" with combining accent -> NFC first, then titlecase
        nfd_input = "chloe\u0301 smith"
        result = process_text(nfd_input, config)
        # After NFC: "chlo\u00e9 smith", after titlecase: "Chlo\u00e9 Smith"
        assert result == "Chlo\u00e9 Smith"

    def test_word_replacement_before_titlecase(self, make_text_config):
        """Word replacement runs before titlecase: replaced words get titlecased."""
        from text_processor import process_text

        config = make_text_config(
            word_replacer={"foo": "bar"},
            titlecase=True,
        )
        result = process_text("foo baz", config)
        # replace "foo"->"bar", then titlecase: "Bar Baz"
        assert result == "Bar Baz"

    def test_char_removal_before_titlecase(self, make_text_config):
        """Character removal runs before titlecase."""
        from text_processor import process_text

        config = make_text_config(remove_chars="#", titlecase=True)
        result = process_text("hello #world", config)
        # remove "#": "hello world", titlecase: "Hello World"
        assert result == "Hello World"

    def test_preposition_removal_before_titlecase(self, make_text_config):
        """Preposition removal runs before titlecase."""
        from text_processor import process_text

        config = make_text_config(
            prepositions_removal=True,
            prepositions=["the"],
            titlecase=True,
        )
        result = process_text("the walking dead", config)
        # remove "the": "walking dead", titlecase: "Walking Dead"
        assert result == "Walking Dead"

    def test_titlecase_before_transliteration(self, make_text_config):
        """Titlecase runs before ASCII transliteration."""
        from text_processor import process_text

        config = make_text_config(titlecase=True, use_ascii=True)
        result = process_text("caf\u00e9 latte", config)
        # titlecase: "Caf\u00e9 Latte", transliterate: "Cafe Latte"
        assert result == "Cafe Latte"

    def test_sanitization_after_transliteration(self, make_text_config):
        """Sanitization runs after transliteration."""
        from text_processor import process_text

        config = make_text_config(use_ascii=True)
        # Input has Unicode + illegal char ":"
        result = process_text("\u00fcber: stuff", config)
        # transliterate: "uber: stuff", sanitize (replace : with space): "uber stuff"
        assert ":" not in result
        assert "uber" in result

    def test_space_replacement_is_last(self, make_text_config):
        """Space replacement is the final step."""
        from text_processor import process_text

        config = make_text_config(space_char=".")
        result = process_text("hello world", config)
        assert result == "hello.world"


class TestProcessTextToggleBehavior:
    """Tests for process_text() - config toggle gating."""

    def test_titlecase_false_skips(self, make_text_config):
        """titlecase=False skips titlecase: input stays lowercase."""
        from text_processor import process_text

        config = make_text_config(titlecase=False)
        result = process_text("hello world", config)
        assert result == "hello world"

    def test_use_ascii_false_preserves_unicode(self, make_text_config):
        """use_ascii=False preserves accented characters."""
        from text_processor import process_text

        config = make_text_config(use_ascii=False)
        result = process_text("Chlo\u00e9", config)
        assert "\u00e9" in result

    def test_prepositions_removal_false_preserves(self, make_text_config):
        """prepositions_removal=False preserves prepositions."""
        from text_processor import process_text

        config = make_text_config(prepositions_removal=False)
        result = process_text("The Walking Dead", config)
        assert "The" in result

    def test_all_toggles_disabled(self, make_text_config):
        """All toggles disabled: only normalize, sanitize, and space replacement run."""
        from text_processor import process_text

        config = make_text_config(
            titlecase=False,
            use_ascii=False,
            prepositions_removal=False,
            word_replacer={},
            remove_chars="",
        )
        result = process_text("hello world", config)
        # Only NFC normalize + sanitize + space replace (space_char=" " is default noop)
        assert result == "hello world"

    def test_all_toggles_enabled(self, make_text_config):
        """All toggles enabled: full pipeline runs in correct order."""
        from text_processor import process_text

        config = make_text_config(
            word_replacer={"scene": "video"},
            remove_chars="#",
            prepositions_removal=True,
            prepositions=["the"],
            titlecase=True,
            use_ascii=True,
            space_char=".",
        )
        # Input: "the scene #caf\u00e9"
        # 1. normalize: "the scene #caf\u00e9"
        # 2. word replace: "the video #caf\u00e9"
        # 3. char remove: "the video caf\u00e9"
        # 4. preposition remove: "video caf\u00e9"
        # 5. titlecase: "Video Caf\u00e9"
        # 6. transliterate: "Video Cafe"
        # 7. sanitize: "Video Cafe" (clean)
        # 8. space replace: "Video.Cafe"
        result = process_text("the scene #caf\u00e9", config)
        assert result == "Video.Cafe"


class TestProcessTextIntegration:
    """Tests for process_text() - full pipeline integration scenarios."""

    def test_realistic_full_pipeline(self, make_text_config):
        """Realistic scenario with NFD, word replacement, illegal chars, Unicode, prepositions."""
        from text_processor import process_text
        import unicodedata

        config = make_text_config(
            word_replacer={"ep": "episode"},
            remove_chars="#",
            prepositions_removal=True,
            prepositions=["the", "a"],
            titlecase=True,
            use_ascii=True,
            space_char="-",
        )
        # NFD input with illegal char, preposition, word replacement, accented chars
        nfd_e_acute = "e\u0301"  # NFD form of e-acute
        input_text = f"the ep #1: caf{nfd_e_acute} sc{nfd_e_acute}ne"
        result = process_text(input_text, config)
        # 1. normalize: "the ep #1: caf\u00e9 sc\u00e9ne"
        # 2. word replace: "the episode #1: caf\u00e9 sc\u00e9ne"
        # 3. char remove (#): "the episode 1: caf\u00e9 sc\u00e9ne"
        # 4. preposition remove (the): "episode 1: caf\u00e9 sc\u00e9ne"
        # 5. titlecase: "Episode 1: Caf\u00e9 Sc\u00e9ne"
        # 6. transliterate: "Episode 1: Cafe Scene"
        # 7. sanitize (: -> -): "Episode 1- Cafe Scene" -> collapses -> "Episode 1- Cafe Scene"
        # 8. space replace: "Episode-1--Cafe-Scene" -> collapse -> "Episode-1-Cafe-Scene"
        # Wait, let's think more carefully:
        # After sanitize: "Episode 1" + "-" (from colon) + " Cafe Scene"
        # = "Episode 1- Cafe Scene" after collapse = "Episode 1- Cafe Scene"
        # Then space replace (space -> -): "Episode-1--Cafe-Scene" -> collapse -> "Episode-1-Cafe-Scene"
        assert ":" not in result
        assert "#" not in result
        assert result.startswith("Episode")
        assert "Cafe" in result
        assert "Scene" in result
        # Verify separator is used
        assert "-" in result

    def test_default_text_config_passthrough(self, default_text_config):
        """Default TextConfig: plain string gets minimal transformation (NFC + sanitize)."""
        from text_processor import process_text

        result = process_text("A Simple Title", default_text_config)
        # Default config: no titlecase, no ascii, no preposition removal
        # space_char=" " (default), remove_chars=",#"
        # So: normalize -> remove "," and "#" -> sanitize -> done
        assert result == "A Simple Title"

    def test_default_config_removes_default_chars(self, default_text_config):
        """Default TextConfig removes comma and hash (default remove_chars=',#')."""
        from text_processor import process_text

        result = process_text("Hello, World #1", default_text_config)
        assert result == "Hello World 1"


class TestProcessTextCaseInteraction:
    """Tests for titlecase vs lowercase precedence."""

    def test_titlecase_overrides_lowercase(self, make_text_config):
        """When both titlecase=True and lowercase=True, titlecase takes precedence."""
        from text_processor import process_text

        config = make_text_config(titlecase=True, lowercase=True)
        result = process_text("hello world", config)
        assert result == "Hello World"

    def test_lowercase_only(self, make_text_config):
        """When only lowercase=True, all text is lowercased."""
        from text_processor import process_text

        config = make_text_config(lowercase=True, titlecase=False)
        result = process_text("Hello World", config)
        assert result == "hello world"
