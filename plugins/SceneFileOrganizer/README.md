# SceneFileOrganizer

Rename and organize scene files based on configurable metadata-driven templates.

SceneFileOrganizer is a [Stash](https://stashapp.cc/) plugin that automatically renames and moves scene files when they are marked as "organized." It is a clean rewrite of the deprecated `renamerOnUpdate` plugin, built with a modular architecture, YAML configuration, and Stash's native GraphQL `MoveFiles` mutation (no direct database writes).

**Minimum Stash version:** v0.22.0

## How It Works

1. You mark a scene as **Organized** in the Stash UI.
2. The plugin's hook fires on `Scene.Update.Post`.
3. The plugin fetches scene metadata (title, date, performers, studio, tags, etc.), selects a filename and path template based on priority rules, renders the templates, and moves the file to its new location via the Stash GraphQL API.

The plugin ships **disabled** with **dry-run ON** by default. You must explicitly enable it and turn off dry-run before any files are moved.

## Installation

### Prerequisites

- **Stash v0.22.0** or later
- **Python 3** (bundled with Stash on most platforms)

### Steps

1. **Copy the plugin folder** into your Stash plugins directory:

   ```
   ~/.stash/plugins/SceneFileOrganizer/
   ```

   On Windows this is typically `C:\Users\<you>\.stash\plugins\SceneFileOrganizer\`.

   The folder should contain `scene_file_organizer.py`, `scene_file_organizer.yml`, `config_loader.py`, and all other `.py` files plus `requirements.txt`.

2. **Install Python dependencies:**

   ```bash
   pip install -r ~/.stash/plugins/SceneFileOrganizer/requirements.txt
   ```

   This installs: `stashapp-tools`, `pyyaml`, and `Unidecode`.

3. **Reload plugins** in Stash: go to **Settings > Plugins** and click **Reload Plugins**, or restart Stash.

4. **Verify** the plugin appears in the plugin list with 5 task buttons: Enable, Disable, Toggle Dry Run, Rename All Scenes, Backfill Organized Scenes.

### First Run

On first run (when no `config.yaml` exists), the plugin generates a fully-commented default `config.yaml` in the plugin folder. Edit this file to set your filename and path templates before enabling the plugin.

### Getting Started

1. Click the **Enable** task button to activate the hook.
2. Leave **dry-run ON** (it defaults to ON for safety).
3. Mark a scene as organized in the Stash UI.
4. Check the **Stash logs** (Logs page or Settings > Logs) to see what the plugin would rename/move.
5. Once you are happy with the output, click **Toggle Dry Run** to turn dry-run OFF and start moving files for real.

## Operation Modes

### Hook Mode (Automatic)

The primary mode. Triggers automatically on `Scene.Update.Post` when a scene is marked organized. The plugin applies five safety guards before processing:

1. Plugin must be **enabled** (via Enable task button)
2. A `hookContext` must exist in the event arguments
3. The `organized` field must be in the update's input fields
4. `organized` must be set to **true** (not false)
5. A `scene_id` must be present

If all guards pass, the plugin processes the scene through the full rename/move pipeline.

### Enable / Disable

Toggle the hook on or off via the Stash plugin task buttons. When disabled, the `Scene.Update.Post` hook still fires but returns immediately without processing.

### Dry Run Toggle

Toggle dry-run mode on or off. When dry-run is **ON** (the default), the plugin logs detailed information about what it would do -- including the old path, new path, matched templates, resolved variables, and associated files -- without actually moving anything. This is the recommended way to preview changes before committing.

### Bulk Rename ("Rename All Scenes")

Process **all scenes** in the Stash database against current templates. Respects the dry-run setting. Displays a progress bar in the Stash UI during processing.

- Configurable delay between scenes via `general.bulk_delay` (default: 1 second) to prevent database locking.
- Reports a summary at completion: processed, moved, skipped, failed counts.

### Backfill ("Backfill Organized Scenes")

Check all **organized** scenes and identify files that do not match their expected path according to current templates. Uses NFC-normalized path comparison for cross-platform consistency (macOS NFD vs Linux NFC).

- **Dry-run ON (audit-only mode):** Reports misplaced files without moving them. Shows actual vs expected path for each mismatch.
- **Dry-run OFF (fix mode):** Moves misplaced files to their expected locations via `process_scene`.
- Reports summary statistics at completion: total, matched, misplaced, would-move, failed, excluded.

## Processing Pipeline

When a scene is processed (by hook, bulk, or backfill), the plugin follows this pipeline:

1. **Fetch** scene data via Stash GraphQL API
2. **Check exclusion rules** -- skip scenes matching excluded tags, studios, or paths
3. **Extract metadata** -- build 25+ template variables from scene data (title, date, performers, studio, tags, technical info, etc.)
4. **Select templates** -- choose filename and path templates by priority: tag > studio > [path-match] > default
5. **Apply tag modifiers** -- per-tag overrides (inverse performer names, per-tag dry-run)
6. **Render templates** -- substitute variables, expand conditional groups
7. **Apply text processing** -- sanitize filenames, apply casing, character replacement, ASCII transliteration
8. **Resolve duplicates** -- check for filename collisions and append suffixes if needed
9. **Move video file** via Stash GraphQL `MoveFiles` mutation
10. **Move associated files** -- rename and move sidecar files (`.srt`, `.vtt`, `.funscript`)
11. **Clean up** empty source folders
12. **Remove trigger tag** if the `clean_tag` modifier is set for the matched tag

## Template System

SceneFileOrganizer uses a two-part template system: **filename templates** control the file name and **path templates** control the directory structure. Both use `$variable` placeholders that are replaced with scene metadata at render time.

### Template Priority

Templates are selected by a priority chain. The first match wins:

**Filename templates:** tag_templates > studio_templates > default

**Path templates:** tag_templates > studio_templates > path_templates > default

- **Tag templates** match when the scene has a tag whose name is a key in the `tag_templates` dict. The first matching tag wins.
- **Studio templates** match when the scene's studio name is a key in the `studio_templates` dict.
- **Path templates** (path only) match when the scene's current file path contains the key string as a substring.
- **Default** is used only when `use_default: true` is set in the config. If `use_default` is `false` (the default), the scene keeps its current filename or path when no other template matches.

### Group Syntax

Curly braces define **conditional groups**: `{$var text}`. If ANY `$variable` inside the braces resolves to an empty string, the ENTIRE group (including all static text) is removed. Otherwise, the variables are substituted and the braces are stripped.

**Example:** `{$date - }$title`
- With date "2024-01-15" and title "Second Ring": produces `2024-01-15 - Second Ring`
- With no date and title "Second Ring": produces `Second Ring` (the entire `{$date - }` group is removed)

This is the recommended way to handle optional variables without leaving stray separators in filenames.

### Special Path Tokens

- **`^*`** in a path template is replaced with the scene's current parent directory. This lets you keep files in their existing folder structure while reorganizing subfolders: `^*/$performer` keeps the current directory and adds a performer subfolder.
- **`$studio_hierarchy`** expands into nested directory segments. For example, if the studio hierarchy is "MindGeek/Brazzers/Deeper", using `$studio_hierarchy` in a path template produces three separate folder levels: `MindGeek/Brazzers/Deeper/`.

## Template Variable Reference

All variables default to an empty string `""` when their data is unavailable. Use group syntax `{$var text}` to handle optional variables cleanly.

| Variable | Description | Example Value | Source |
|----------|-------------|---------------|--------|
| `$title` | Scene title | `Second Ring` | scene.title |
| `$date` | Scene date (raw ISO format) | `2024-01-15` | scene.date |
| `$year` | Year extracted from date | `2024` | Parsed from date |
| `$date_format` | Date formatted per `formatting.date_format` | `2024-01-15` | strftime of scene.date |
| `$rating` | Scene rating (formatted per `formatting.rating_format`) | `85` | scene.rating100 |
| `$performer` | Performer names joined by separator | `Doe, Jane Smith, John` | Sorted, filtered, limited by performers config |
| `$stashid_performer` | Performer StashDB IDs joined by separator | `abc-123 def-456` | First stash_id per performer |
| `$studio` | Studio name | `Deeper` | scene.studio.name |
| `$parent_studio` | Parent studio name | `Vixen Media Group` | studio.parent_studio.name |
| `$studio_family` | Root of studio hierarchy | `MindGeek` | First in hierarchy chain |
| `$studio_hierarchy` | Full hierarchy as path | `MindGeek/Brazzers/Deeper` | Joined with `/` separator |
| `$studio_code` | Scene studio code | `deeper_105146` | scene.code |
| `$tags` | Tags joined by separator (filtered by whitelist/blacklist) | `anal blowjob` | Tag names from tags config |
| `$height` | Video height label | `1080p`, `4k`, `720p` | Mapped from pixel height |
| `$resolution` | Resolution category | `HD`, `UHD`, `SD`, `VERTICAL` | Mapped from dimensions |
| `$duration` | Scene duration | `3600.5` or `01:00:00` | Raw seconds or formatted via `formatting.duration_format` |
| `$bitrate` | Video bitrate in Mbps | `8.54` | file.bit_rate / 1,000,000 |
| `$video_codec` | Video codec (uppercase) | `H264`, `HEVC` | file.video_codec |
| `$audio_codec` | Audio codec (uppercase) | `AAC`, `OPUS` | file.audio_codec |
| `$oshash` | OSHash fingerprint | `abc123def456` | file.fingerprints |
| `$checksum` | Checksum/MD5 fingerprint | `abc123def456` | file.fingerprints |
| `$movie_title` | Movie/group title | `Best Of 2024` | First group.name |
| `$movie_year` | Movie/group release year | `2024` | First 4 chars of group.date |
| `$movie_scene` | Scene index in movie | `scene 3` | group.scene_index |
| `$stashid_scene` | Scene StashDB ID | `abc-123-def` | First scene.stash_ids entry |

## Configuration Guide

All configuration lives in `config.yaml` in the plugin folder. The plugin generates a fully-commented default on first run. Every key shown below includes its type and default value.

### `filename` -- Filename Templates

Controls what the file is named.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tag_templates` | dict | `{}` | Tag-based templates. Key = tag name, value = template string. Highest priority. |
| `studio_templates` | dict | `{}` | Studio-based templates. Key = studio name, value = template string. |
| `use_default` | bool | `false` | Whether to apply the default template when no tag/studio template matches. |
| `default` | string | `"$date $title"` | Default filename template. Only used when `use_default` is `true`. |

**Example:**

```yaml
filename:
  tag_templates:
    "!1. Western": "$date $performer - $title [$studio]"
    "!1. JAV": "$title"
  studio_templates:
    "Deeper": "[$studio] $title"
  use_default: true
  default: "$date $title"
```

### `path` -- Path Templates

Controls where the file is moved.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tag_templates` | dict | `{}` | Tag-based path templates. Key = tag name, value = path template. Highest priority. |
| `studio_templates` | dict | `{}` | Studio-based path templates. Key = studio name, value = path template. |
| `path_templates` | dict | `{}` | Path-match templates. Key = source path substring, value = destination template. Uses substring matching (`in` operator). |
| `use_default` | bool | `false` | Whether to apply the default path template when no other matches. |
| `default` | string | `"^*/$performer"` | Default path template. `^*` = current parent directory. |
| `non_organized` | string | `""` | Path template for scenes that are un-organized (organized set to false). Empty = skip. |

**Example:**

```yaml
path:
  tag_templates:
    "!1. Western": "/media/videos/western/$studio/$performer"
  studio_templates:
    "Deeper": "/media/videos/$studio_hierarchy"
  path_templates:
    "/unsorted/": "/media/videos/sorted/$studio/$performer"
  use_default: true
  default: "^*/$performer"
```

### `tag_options` -- Per-Tag Behavior Modifiers

Override behavior for scenes that match specific tag templates. Each key must be a tag name that also exists in `filename.tag_templates` or `path.tag_templates`. Values are dicts with optional boolean modifier keys.

| Modifier | Type | Default | Description |
|----------|------|---------|-------------|
| `clean_tag` | bool | `false` | Remove the matching tag from the scene after a successful (non-dry-run) move. |
| `inverse_performer` | bool | `false` | Swap performer name format from "Last, First" to "First Last". |
| `dry_run` | bool | `false` | Force dry-run mode for scenes matching this tag, overriding the global setting. |

All modifiers default to `false`. Modifiers combine (e.g., `clean_tag` + `inverse_performer` both apply). Unknown keys or non-boolean values are rejected with clear error messages.

**Example:**

```yaml
tag_options:
  "!1. Western":
    clean_tag: true
    inverse_performer: true
  "!1. JAV":
    dry_run: true
```

### `text` -- Text Processing

Controls how rendered template output is transformed before it becomes a filename or path segment.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `space_char` | string | `" "` | Character to replace spaces with in filenames/paths. |
| `field_whitespace_separator` | string | `""` | Separator to replace spaces within individual variable values before rendering. Empty = no replacement. |
| `field_replacer` | dict | `{}` | Per-variable character replacement. Key = `"$variable"`, value = `{"replace": "char", "with": "replacement"}`. |
| `word_replacer` | dict | `{}` | Word-level replacements applied to all text. Key = word to find, value = replacement. |
| `remove_chars` | string | `",#"` | Characters to remove from all generated text. Each character in the string is removed individually. |
| `lowercase` | bool | `false` | Convert all text to lowercase. |
| `titlecase` | bool | `false` | Convert all text to title case. |
| `prepositions_removal` | bool | `false` | Remove common prepositions from text. |
| `prepositions` | list | `["a", "an", "the", ...]` | List of prepositions to remove (when `prepositions_removal` is `true`). Default includes: a, an, the, of, in, on, at, for, to, and, but, or. |
| `use_ascii` | bool | `false` | Transliterate non-ASCII characters to ASCII equivalents. Requires the Unidecode library. |

**`field_replacer` example:**

```yaml
text:
  field_replacer:
    "$studio":
      replace: "'"
      with: ""
    "$performer":
      replace: "-"
      with: " "
```

### `formatting` -- Date, Duration, and Rating Formatting

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `date_format` | string | `"%Y-%m-%d"` | Python strftime format string for the `$date_format` variable. |
| `duration_format` | string | `""` | Format string for duration (e.g., `"%H:%M:%S"`). Empty = raw seconds. |
| `rating_format` | string | `"{}"` | Python format string for rating. `{}` is replaced with the raw `rating100` value. Examples: `"{}/5"`, `"{:.1f}"`. |

### `performers` -- Performer Display

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `separator` | string | `" "` | Separator between multiple performer names. |
| `limit` | int | `3` | Maximum number of performers to include. |
| `keep_up_to_limit` | bool | `false` | When the number of performers exceeds `limit`: if `true`, include the first `limit` performers. If `false`, return empty string (all or nothing). |
| `sort` | string | `"id"` | Sort order for performers. Options: `id` (numeric ascending), `name` (alphabetical), `rating` (highest rating100 first), `favorite` (favorites first), `mix` (favorites first, then rating desc, then name), `mixid` (favorites first, then rating desc, then ID). |
| `ignore_gender` | list | `[]` | List of gender strings to exclude from the performer list (e.g., `["MALE"]`). |
| `prevent_title_duplicate` | bool | `false` | If `true`, clears the `$performer` variable when it matches the scene title exactly. |

### `studios` -- Studio Display

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `squeeze_names` | bool | `false` | Remove spaces from studio names (e.g., "Vixen Media" becomes "VixenMedia"). |
| `max_hierarchy_depth` | int | `0` | Maximum depth for `$studio_hierarchy`. `0` = unlimited (traverse full parent chain). |

### `tags` -- Tag Filtering (for `$tags` variable)

Controls which tags appear in the `$tags` template variable. Does not affect tag template matching.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `separator` | string | `" "` | Separator between multiple tag names. |
| `whitelist` | list | `[]` | Only include tags whose name is in this list. Empty = all tags included. |
| `blacklist` | list | `[]` | Exclude tags whose name is in this list. Applied after whitelist. |

### `paths` -- Path Management

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `prevent_consecutive_folders` | bool | `true` | Remove consecutive duplicate folder names in the path (e.g., `Deeper/Deeper/` becomes `Deeper/`). |
| `remove_empty_folders` | bool | `true` | Remove empty source folders after moving a file. |
| `single_performer_in_path` | bool | `true` | Use only the first performer in path templates (even if multiple appear in the filename). |
| `keep_existing_performer_folder` | bool | `true` | If a performer name already appears as a folder in the current path, keep that performer for the path instead of using the first one. |
| `no_performer_folder` | bool | `false` | When `true` and the performer variable is empty, substitute `"NoPerformer"` as the folder name. |
| `max_length` | int | `240` | Maximum total path length (directory + filename). |
| `length_reduction_order` | list | (see below) | Order in which `$variable` values are progressively removed to reduce path length when it exceeds `max_length`. |

**Default `length_reduction_order`:**

```yaml
length_reduction_order:
  - "$video_codec"
  - "$audio_codec"
  - "$resolution"
  - "$tags"
  - "$rating"
  - "$height"
  - "$studio_family"
  - "$studio"
  - "$parent_studio"
  - "$performer"
```

### `files` -- File Handling

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `associated_extensions` | list | `["srt", "vtt", "funscript"]` | File extensions for associated/sidecar files to move alongside the video. |
| `duplicate_suffixes` | list | `["", "_1", "_2", "_3", "_4", "_5"]` | Suffixes tried when checking for duplicate filenames. The first suffix that produces a unique filename is used. |
| `max_duplicate_retries` | int | `99` | Maximum number of duplicate suffix retries before giving up. |
| `filename_as_title` | bool | `false` | Use the filename (without extension) as the scene title if the title is empty. |

### `exclusions` -- Exclusion Patterns

Scenes matching any exclusion pattern are skipped entirely. No renaming or moving occurs.

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `tags` | list | `[]` | Tag names that cause a scene to be skipped. |
| `studios` | list | `[]` | Studio names that cause a scene to be skipped. |
| `paths` | list | `[]` | Path substrings that cause a scene to be skipped. |

### `general` -- General Settings

| Key | Type | Default | Description |
|-----|------|---------|-------------|
| `log_file` | string | `""` | Path to a file for logging rename operations. Empty = no file logging. |
| `debug` | bool | `false` | Enable debug-level logging. |
| `bulk_delay` | int | `1` | Delay in seconds between scenes during bulk rename and backfill operations. Prevents database locking. |

## Configuration Examples

Complete, copy-pasteable `config.yaml` examples for common organization scenarios. Each example shows only the relevant sections -- all unspecified keys use their defaults.

### Example 1: Studio-Based Organization

**Use case:** Organize files into a studio hierarchy folder structure with studio-prefixed filenames. Ideal for users who browse by studio/network.

```yaml
filename:
  use_default: true
  default: "[$studio] $date $title"

path:
  use_default: true
  default: "/media/videos/$studio_hierarchy/$performer"

performers:
  separator: ", "
  limit: 3
  sort: "name"
```

**Result:** A scene from studio "Deeper" (under Vixen Media Group), dated 2024-01-15, titled "Second Ring", with performer Jane Doe:

```
/media/videos/Vixen Media Group/Deeper/Jane Doe/[Deeper] 2024-01-15 Second Ring.mp4
```

The `$studio_hierarchy` variable expands into nested folders for the full studio parent chain. The `$performer` in the path uses only the first performer by default (`paths.single_performer_in_path: true`).

### Example 2: Performer-Based Folders

**Use case:** Organize by performer name with studio info in the filename. Ideal for users who browse by performer.

```yaml
filename:
  use_default: true
  default: "$date $performer - $title {[$studio]}"

path:
  use_default: true
  default: "/media/videos/$performer"

paths:
  single_performer_in_path: true

performers:
  separator: ", "
  limit: 2
  keep_up_to_limit: true
  sort: "name"
```

**Result:** A scene dated 2024-01-15, titled "Second Ring", studio "Deeper", with performers Jane Doe and John Smith:

```
/media/videos/Jane Doe/2024-01-15 Jane Doe John Smith - Second Ring [Deeper].mp4
```

Note: The `{[$studio]}` group syntax means the `[Deeper]` suffix is only included when a studio name exists. If the scene has no studio, the brackets and space are removed cleanly.

### Example 3: Tag-Based Routing with Modifiers

**Use case:** Route different content categories to different templates using tags as workflow triggers. Tags with `clean_tag` are automatically removed after processing.

```yaml
filename:
  tag_templates:
    "!1. Western": "$date $performer - $title {[$studio]}"
    "!1. JAV": "$title {[$studio_code]}"
    "!1. Anime": "$title {$height}"
  use_default: true
  default: "$date $title"

path:
  tag_templates:
    "!1. Western": "/media/videos/western/$studio/$performer"
    "!1. JAV": "/media/videos/jav/$studio"
    "!1. Anime": "/media/videos/anime/$studio"
  use_default: true
  default: "/media/videos/unsorted/$studio"

tag_options:
  "!1. Western":
    clean_tag: true
    inverse_performer: true
  "!1. JAV":
    clean_tag: true
  "!1. Anime":
    clean_tag: true
    dry_run: true
```

The `!1.` prefix in tag names is a Stash convention for sorting -- tags starting with `!` sort to the top in the Stash UI, making them easy to apply as workflow triggers.

**Tag matching behavior:** The first matching tag wins. If a scene has both `!1. Western` and `!1. JAV`, the Western template is used (order depends on the tag order in Stash).

**Modifier effects:**
- `clean_tag: true` -- the trigger tag is removed from the scene after a successful (non-dry-run) move, keeping your tag list clean
- `inverse_performer: true` -- swaps "Doe, Jane" to "Jane Doe" in the performer variable for that tag's template
- `dry_run: true` -- forces dry-run mode for scenes matching the Anime tag, regardless of the global dry-run setting (useful for testing new templates)

**Results:**

A Western scene tagged `!1. Western`, studio "Deeper", performer "Doe, Jane", dated 2024-01-15, titled "Second Ring":

```
/media/videos/western/Deeper/Jane Doe/2024-01-15 Jane Doe - Second Ring [Deeper].mp4
```

(The `!1. Western` tag is removed from the scene after the move.)

A JAV scene tagged `!1. JAV`, studio code "carib-010124-001", titled "Beautiful Girl":

```
/media/videos/jav/Caribbean/Beautiful Girl [carib-010124-001].mp4
```

### Example 4: Minimal Setup (Quick Start)

**Use case:** Just rename files in place using basic metadata. No moving, no folders, no complex templates. The simplest possible configuration.

```yaml
filename:
  use_default: true
  default: "$date $title"
```

**Result:** A scene dated 2024-01-15 titled "Second Ring", currently at `/downloads/scene123.mp4`:

```
/downloads/2024-01-15 Second Ring.mp4
```

With no path template active (`path.use_default` defaults to `false`), the file stays in its current directory. Only the filename changes.

### Example 5: Bulk Rename with Exclusions

**Use case:** Rename and organize all files, but skip certain studios, tagged content, and already-sorted directories.

```yaml
filename:
  use_default: true
  default: "$date $performer - $title {[$studio]}"

path:
  use_default: true
  default: "/media/videos/$studio/$performer"

exclusions:
  tags:
    - "!DoNotRename"
  studios:
    - "StudioToSkip"
    - "AnotherStudio"
  paths:
    - "/media/videos/sorted/"
    - "/media/videos/archive/"
```

**How exclusions work:** Exclusions use OR logic -- if a scene matches **any** exclusion rule (any listed tag, studio, or path pattern), it is skipped entirely. No renaming or moving occurs.

- **Tag exclusions:** Case-insensitive exact match against scene tag names.
- **Studio exclusions:** Case-insensitive exact match against the scene's studio name.
- **Path exclusions:** Regex pattern matched against the scene's current file path.

**Result:** When running "Rename All Scenes":
- A scene tagged `!DoNotRename` is skipped (log shows: `excluded by tag: !DoNotRename`)
- A scene from "StudioToSkip" is skipped (log shows: `excluded by studio: StudioToSkip`)
- A scene at `/media/videos/sorted/Deeper/scene.mp4` is skipped (log shows: `excluded by path: /media/videos/sorted/`)
- All other scenes are renamed and moved per the templates

### Example 6: Path-Match Templates

**Use case:** Route files from different source directories to different organized destinations. Useful when files arrive in multiple download/import folders.

```yaml
filename:
  use_default: true
  default: "$date $title {[$studio]}"

path:
  path_templates:
    "/downloads/videos/": "/media/videos/$studio/$performer"
    "/downloads/clips/": "/media/clips/$studio"
    "/import/": "/media/videos/$studio_hierarchy/$performer"
  use_default: true
  default: "^*/$performer"
```

**How path matching works:** The key in `path_templates` is checked as a substring against the scene's current file path using Python's `in` operator. The first matching key wins.

**Template priority reminder:** tag > studio > path-match > default. Path-match templates are only checked when no tag or studio template matches.

**Results:**

A scene currently at `/downloads/videos/scene.mp4`, studio "Deeper", performer "Jane Doe", dated 2024-01-15:

```
/media/videos/Deeper/Jane Doe/2024-01-15 Second Ring [Deeper].mp4
```

A scene currently at `/import/batch1/raw.mp4`, studio "Deeper" (under Vixen Media Group), performer "Jane Doe":

```
/media/videos/Vixen Media Group/Deeper/Jane Doe/2024-01-15 Second Ring [Deeper].mp4
```

A scene currently at `/other/location/video.mp4` (no path-match hit, falls through to default):

```
/other/location/Jane Doe/2024-01-15 Second Ring [Deeper].mp4
```

(The default `^*/$performer` keeps the current directory and adds a performer subfolder.)

## Troubleshooting

Common issues and how to diagnose them. Enable dry-run mode and check **Stash logs** (Settings > Logs) for diagnostic output.

### 1. Files not moving (nothing happens when marking as organized)

**Cause: Plugin not enabled**
The hook fires but returns immediately when the plugin is disabled.

- **Solution:** Click the **Enable** task button in the Stash plugin panel. Check Stash logs for `SceneFileOrganizer enabled.`

**Cause: Dry-run mode is ON (default)**
The plugin logs what it would do but does not actually move files. Dry-run is ON by default for safety.

- **Solution:** Click **Toggle Dry Run** to switch to live mode. Look for the `[DRY RUN]` prefix in log entries. When dry-run is off, you will see `Moved:` entries instead.

**Cause: No matching template**
If `use_default` is `false` (the default) and no tag or studio template matches, the plugin has no template to apply and skips the scene silently.

- **Solution:** Set `use_default: true` in the `filename` and/or `path` sections of `config.yaml`, or ensure the scene has a matching tag or studio template.

### 2. Files not moving (plugin fires but skips scene)

**Cause: Scene matches an exclusion rule**
The scene is being filtered out by a tag, studio, or path exclusion pattern.

- **Solution:** Check logs for `excluded by` followed by the matching rule (e.g., `excluded by tag: !DoNotRename`). Review the `exclusions` section in `config.yaml`.

**Cause: Destination path is not under a Stash library path**
The plugin validates that the destination directory is inside one of your configured Stash library paths.

- **Solution:** Check logs for `not under any library path`. Ensure your path template resolves to a directory inside one of your configured Stash library paths (Settings > Library).

**Cause: Scene has no files attached**
The scene entry in Stash has no associated video file.

- **Solution:** Check logs for `has no files`. Verify the scene has at least one file in Stash (check the scene detail page for the Files tab).

**Cause: Scene is already at the target path**
If the computed destination matches the current location, the plugin skips the scene.

- **Solution:** Check logs for `already at target path`. This is expected behavior -- the scene is already where it should be.

### 3. Unexpected file paths or names

**Cause: Wrong template matched (priority confusion)**
The template priority chain (tag > studio > path-match > default) may have matched a different template than expected.

- **Solution:** Enable dry-run and mark the scene organized. Check the log for `Filename template:` and `Path template:` lines which show which template matched and why (e.g., `tag: !1. Western`, `studio: Deeper`, `default`, or `none`).

**Cause: Variable is empty, causing missing parts**
A template variable resolved to an empty string, leaving gaps or stray separators in the output.

- **Solution:** Check dry-run log for `Variables:` which shows all resolved variable values. Use group syntax `{$var text}` to gracefully handle empty variables -- the entire group is removed when any variable inside is empty.

**Cause: Text processing removing unexpected characters**
The `text.remove_chars` setting (default: `",#"`) removes certain characters from all generated text. The `text.space_char` setting may replace spaces.

- **Solution:** Check the `text.remove_chars` value in your `config.yaml`. If characters you want to keep are being removed, edit the string. Check `text.space_char` if spaces are being replaced with unexpected characters.

### 4. Duplicate filename conflicts

**Cause: Two scenes resolve to the same filename in the same directory**
The plugin automatically appends `_1`, `_2`, etc. suffixes to avoid overwriting existing files.

- **Solution:** Check logs for `duplicate detected, using` which shows the suffixed filename. If the maximum retries are exceeded (default: 99), the scene is skipped. Adjust `files.max_duplicate_retries` if needed, or revise your templates to include more unique variables (e.g., `$oshash`, `$stashid_scene`).

### 5. Path too long

**Cause: Combined path + filename exceeds `paths.max_length` (default: 240)**
The plugin automatically removes variable values in the order specified by `paths.length_reduction_order` until the path fits.

- **Solution:** If critical variables are being removed, consider shortening your templates, increasing `paths.max_length`, or reordering `paths.length_reduction_order` to preserve the variables you care about most (variables at the end of the list are removed first).

### 6. Config validation errors on startup

**Cause: Unknown config key or typo**
The plugin strictly validates all config keys and rejects unknown entries.

- **Solution:** Check logs for `Config validation error`. The error message names the invalid key and lists all valid keys for that section. Fix the typo or remove the unknown key.

**Cause: Invalid tag_options entry**
Each `tag_options` entry must be a dict with only `clean_tag`, `inverse_performer`, and/or `dry_run` keys, all with boolean values.

- **Solution:** Check logs for `tag_options` error messages. Ensure values are `true`/`false` (not strings or numbers). Ensure tag_options keys match a tag name that exists in `filename.tag_templates` or `path.tag_templates` (orphan entries produce a warning).

### 7. Associated files not moving

**Cause: File extension not in `files.associated_extensions`**
Only files with extensions listed in `associated_extensions` are discovered and moved alongside the video.

- **Solution:** Add the extension to the `files.associated_extensions` list. Default extensions: `srt`, `vtt`, `funscript`. Extensions should be listed without a leading dot.

**Cause: Associated file stem does not match video file stem**
Associated files are found by matching the video file's stem (filename without extension). The associated file must share the same base name, with optional suffixes before the extension (e.g., `scene.en.srt` matches `scene.mp4`).

- **Solution:** Ensure the associated file shares the same stem as the video file. For example, `My Scene.srt` matches `My Scene.mp4`, and `My Scene.en.srt` also matches.

### 8. Backfill shows many misplaced files

**Cause: Templates changed since files were originally organized**
After updating your templates, previously organized files will not match the new expected paths.

- **Solution:** This is expected behavior. Run backfill with dry-run ON (audit mode) first to review which files would be moved and where. Then toggle dry-run OFF and run backfill again to fix them.

**Cause: Unicode normalization differences (macOS NFD vs Linux NFC)**
macOS stores filenames in NFD form while Linux uses NFC. The plugin uses NFC normalization for comparison, but the filesystem may report different byte sequences.

- **Solution:** The plugin handles this automatically using NFC-normalized path comparison. If you see false positives, ensure your Stash library paths use consistent Unicode encoding. Re-running backfill with dry-run OFF will normalize the paths.

## Tips and Best Practices

- **Always start with dry-run enabled.** Test with a few scenes before bulk processing your entire library. Check the logs to verify templates produce the expected results.
- **Use the Backfill task periodically** to catch files that drifted from their expected paths after template changes.
- **Tag templates with `!1.` prefix** sort to the top in the Stash UI tag list, making them easy to apply as workflow triggers.
- **The `clean_tag` modifier** lets you use tags as one-shot workflow triggers that auto-remove after processing. Apply tag, mark organized, tag disappears.
- **Keep `general.bulk_delay` at 1+ seconds** for large libraries to avoid database locking during bulk rename or backfill operations.
- **Use group syntax `{$var text}`** for optional variables. The entire group is removed if any variable inside is empty, preventing stray separators or brackets.
- **Use `$studio_hierarchy` in path templates** for automatic nested folder structures that follow the studio's parent chain.
- **Set `performers.sort` to `"name"`** for predictable alphabetical ordering of performer names in filenames.

## Credits

SceneFileOrganizer is a successor to the archived [renamerOnUpdate](https://github.com/stashapp/CommunityScripts) plugin, rebuilt from scratch with a modular architecture, strict YAML configuration validation, and the Stash GraphQL `MoveFiles` mutation.

- **Stash:** [https://stashapp.cc/](https://stashapp.cc/)
- **CommunityScripts:** [https://github.com/stashapp/CommunityScripts](https://github.com/stashapp/CommunityScripts)
