"""Pure text transformation functions for SceneFileOrganizer.

Each function is stateless (string in, string out) with no filesystem access
or Stash connection. Functions accept specific config values rather than the
full Config object, for independent testability.

Processing pipeline order:
  1. normalize_unicode (NFC) - always first
  2. replace_words (three modes)
  3. remove_chars
  4. remove_prepositions (when enabled)
  5. apply_titlecase (when enabled)
  6. transliterate_ascii (when enabled)
  7. sanitize_filename
  8. replace_spaces

The process_text() orchestrator wires all functions into the strict order
and gates conditional steps on TextConfig toggle values.
"""

import re
import unicodedata


# =============================================================================
# NFC Unicode Normalization
# =============================================================================


def normalize_unicode(text: str) -> str:
    """NFC-normalize text. Must be the first processing step.

    Converts decomposed Unicode (NFD) to composed form (NFC).
    This ensures consistent byte representation regardless of
    the source filesystem (macOS APFS uses NFD, Linux ext4 stores verbatim).

    Args:
        text: Input text, possibly in NFD or mixed normalization form.

    Returns:
        NFC-normalized text.
    """
    return unicodedata.normalize("NFC", text)


# =============================================================================
# Word Replacement (Three Modes)
# =============================================================================


def replace_words(text: str, word_replacer: dict) -> str:
    """Apply word-level replacements in three modes.

    Config format:
        New format: {"match": ["replacement", "mode"]}
        Legacy format: {"match": "replacement"} (treated as whole-word mode)

    Modes:
        "word" (default): Whole-word matching using \\b regex boundaries.
        "regex": Raw regex pattern matching.
        "any": Any-substring literal matching.

    Rules apply sequentially in config order (chained output).
    All matching is case-insensitive.

    Args:
        text: Input text to process.
        word_replacer: Dict mapping patterns to replacements.

    Returns:
        Text with all replacements applied.
    """
    for pattern, params in word_replacer.items():
        if isinstance(params, list):
            replacement = params[0] if params else ""
            mode = params[1] if len(params) > 1 else "word"
        else:
            replacement = str(params)
            mode = "word"

        if mode == "word":
            text = re.sub(
                r"\b" + re.escape(pattern) + r"\b",
                replacement,
                text,
                flags=re.IGNORECASE,
            )
        elif mode == "regex":
            text = re.sub(pattern, replacement, text, flags=re.IGNORECASE)
        elif mode == "any":
            text = re.sub(
                re.escape(pattern), replacement, text, flags=re.IGNORECASE
            )

    return text


# =============================================================================
# Character Removal
# =============================================================================


def remove_chars(text: str, chars_to_remove: str) -> str:
    """Remove specified characters from text.

    Args:
        text: Input text.
        chars_to_remove: String of characters to remove (each char individually).

    Returns:
        Text with specified characters removed.
    """
    for char in chars_to_remove:
        text = text.replace(char, "")
    return text


# =============================================================================
# Preposition Removal
# =============================================================================

# Compiled pattern for collapsing whitespace after preposition removal
_WHITESPACE_RE = re.compile(r"\s+")


def remove_prepositions(text: str, prepositions: list) -> str:
    """Remove prepositions from all positions, whole-word matching only.

    Case-insensitive. "The Walking Dead" -> "Walking Dead".
    "the" inside "theater" is NOT removed (word boundary matching).

    Args:
        text: Input text.
        prepositions: List of preposition strings to remove.

    Returns:
        Text with prepositions removed and whitespace cleaned up.
    """
    for prep in prepositions:
        text = re.sub(
            r"\b" + re.escape(prep) + r"\b",
            "",
            text,
            flags=re.IGNORECASE,
        )
    # Clean up multiple spaces left by removal
    text = _WHITESPACE_RE.sub(" ", text).strip()
    return text


# =============================================================================
# Custom Titlecase
# =============================================================================


def apply_titlecase(text: str) -> str:
    """Capitalize first letter of each word, preserving acronyms and internal caps.

    Rules (from CONTEXT.md locked decisions):
    - All-caps words (2+ chars): preserve as acronyms ("BBC" stays "BBC")
    - Mixed-case words: preserve as-is ("McDonald" stays "McDonald")
    - All-lowercase words: capitalize first letter ("hello" -> "Hello")
    - First word: always capitalize regardless of other rules

    Never uses str.title().

    Args:
        text: Input text.

    Returns:
        Titlecased text with acronyms and mixed-case words preserved.
    """
    if not text:
        return text

    words = text.split()
    result = []

    for i, word in enumerate(words):
        if not word:
            continue

        # Extract leading non-alpha characters (if any) for preservation
        # This handles edge cases but keeps the logic simple

        # All-uppercase (2+ alpha chars) -> acronym, preserve
        alpha_chars = [c for c in word if c.isalpha()]
        if len(alpha_chars) >= 2 and all(c.isupper() for c in alpha_chars):
            result.append(word)
        # Mixed case (has both upper and lower) -> preserve as-is
        elif not word.islower() and not word.isupper() and any(c.isupper() for c in word):
            # First word with leading lowercase gets capitalized
            if i == 0 and word[0].islower():
                result.append(word[0].upper() + word[1:])
            else:
                result.append(word)
        # All lowercase (or single char) -> capitalize first letter
        else:
            result.append(word[0].upper() + word[1:])

    return " ".join(result)


# =============================================================================
# ASCII Transliteration
# =============================================================================


def transliterate_ascii(text: str) -> str:
    """Transliterate Unicode to ASCII equivalents.

    Uses the Unidecode library when available. Falls back to stripping
    non-ASCII characters via encode/decode if Unidecode is not installed.

    Args:
        text: Input text (may contain Unicode characters).

    Returns:
        ASCII-equivalent text.
    """
    try:
        from unidecode import unidecode

        return unidecode(text)
    except ImportError:
        # Fallback: strip non-ASCII characters
        return text.encode("ascii", "ignore").decode("ascii")


# =============================================================================
# Filename Sanitization
# =============================================================================

# OS-illegal characters: \ / : * ? " < > | and control chars \x00-\x1f
_ILLEGAL_CHARS_RE = re.compile(r'[\\/:\*\?"<>|\x00-\x1f]')

# Windows reserved names (case-insensitive stem check)
_WINDOWS_RESERVED = frozenset([
    "CON", "PRN", "AUX", "NUL",
    "COM1", "COM2", "COM3", "COM4", "COM5", "COM6", "COM7", "COM8", "COM9",
    "LPT1", "LPT2", "LPT3", "LPT4", "LPT5", "LPT6", "LPT7", "LPT8", "LPT9",
])


def sanitize_filename(text: str, separator: str = " ") -> str:
    """Sanitize text for use as a filename component.

    Replaces OS-illegal characters with the configured separator, collapses
    consecutive separators, strips leading/trailing separators and dots,
    and detects Windows reserved names.

    Per CONTEXT.md locked decision: illegal characters are REPLACED with
    separator, not removed entirely (preserves word boundaries).

    Args:
        text: Input text to sanitize.
        separator: Character to replace illegal chars with (default: space).

    Returns:
        Filesystem-safe text.
    """
    # Replace illegal chars with separator
    text = _ILLEGAL_CHARS_RE.sub(separator, text)

    # Collapse consecutive separators (only if separator is non-empty)
    if separator:
        escaped_sep = re.escape(separator)
        text = re.sub(escaped_sep + "+", separator, text)

    # Strip leading/trailing separator, whitespace, and dots
    strip_chars = separator + " ." if separator != " " else " ."
    text = text.strip(strip_chars)

    # Check Windows reserved names (check stem only, ignoring extension)
    if "." in text:
        stem, ext = text.rsplit(".", 1)
        if stem.upper() in _WINDOWS_RESERVED:
            text = "_" + stem + "." + ext
    else:
        if text.upper() in _WINDOWS_RESERVED:
            text = "_" + text

    return text


# =============================================================================
# Space Replacement
# =============================================================================


def replace_spaces(text: str, separator: str) -> str:
    """Replace whitespace with the configured separator character.

    Collapses consecutive whitespace into a single separator instance.
    This is always the last step in the processing pipeline.

    Args:
        text: Input text.
        separator: Character to replace spaces with.

    Returns:
        Text with spaces replaced by separator.
    """
    # Replace all whitespace sequences with separator
    text = re.sub(r"\s+", separator, text)

    # Collapse consecutive separators (only if separator is not a space)
    if separator and separator != " ":
        escaped_sep = re.escape(separator)
        text = re.sub(escaped_sep + "+", separator, text)

    # Strip leading/trailing separator
    if separator:
        text = text.strip(separator)

    return text


# =============================================================================
# Pipeline Orchestrator
# =============================================================================


def process_text(text: str, config) -> str:
    """Process text through the full transformation pipeline.

    Executes all text transformation functions in strict order.
    Conditional steps are gated on TextConfig toggle values. The orchestrator
    is the public API that downstream phases (filename/path building) call.

    Pipeline order:
      1. normalize_unicode — always
      2. replace_words — if config.word_replacer is non-empty
      3. remove_chars — if config.remove_chars is non-empty
      4. remove_prepositions — if config.prepositions_removal is True
      5. apply_titlecase — if config.titlecase is True
         OR text.lower() — if config.lowercase is True and titlecase is False
      6. transliterate_ascii — if config.use_ascii is True
      7. sanitize_filename — always
      8. replace_spaces — if config.space_char != " "

    Args:
        text: Input text to process.
        config: TextConfig instance with processing settings.

    Returns:
        Fully processed, filesystem-safe text.
    """
    # Fast path for empty input
    if not text:
        return text

    # 1. NFC normalization — always first
    text = normalize_unicode(text)

    # 2. Word replacement — conditional on non-empty replacer
    if config.word_replacer:
        text = replace_words(text, config.word_replacer)

    # 3. Character removal — conditional on non-empty remove_chars
    if config.remove_chars:
        text = remove_chars(text, config.remove_chars)

    # 4. Preposition removal — conditional on toggle
    if config.prepositions_removal:
        text = remove_prepositions(text, config.prepositions)

    # 5. Titlecase or lowercase — titlecase takes precedence
    if config.titlecase:
        text = apply_titlecase(text)
    elif config.lowercase:
        text = text.lower()

    # 6. ASCII transliteration — conditional on toggle
    if config.use_ascii:
        text = transliterate_ascii(text)

    # 7. Filename sanitization — always
    text = sanitize_filename(text, config.space_char)

    # 8. Space replacement — conditional on non-space separator
    if config.space_char != " ":
        text = replace_spaces(text, config.space_char)

    return text
