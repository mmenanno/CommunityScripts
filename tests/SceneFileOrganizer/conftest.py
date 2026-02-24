"""Shared pytest fixtures for SceneFileOrganizer tests."""

import sys
import os
from dataclasses import replace
from unittest.mock import MagicMock

import pytest

# Add plugin directory to sys.path so tests can import the plugin modules
sys.path.insert(
    0, os.path.join(os.path.dirname(__file__), "..", "..", "plugins", "SceneFileOrganizer")
)

from config_loader import (
    FilenameConfig,
    FormattingConfig,
    PathConfig,
    PerformerConfig,
    StudioConfig,
    TagConfig,
    TextConfig,
)


@pytest.fixture
def mock_server_connection():
    """Return a dict matching the stdin JSON server_connection structure from Stash."""
    return {
        "Scheme": "http",
        "Host": "localhost",
        "Port": 9999,
        "SessionCookie": {
            "Name": "session",
            "Value": "test-cookie-value",
            "Path": "",
            "Domain": "",
            "Expires": "",
            "MaxAge": 0,
            "Secure": False,
            "HttpOnly": False,
            "SameSite": 0,
            "Raw": "",
            "Unparsed": None,
        },
        "Dir": "/root/.stash",
        "PluginDir": "/tmp/test-plugin-dir",
    }


@pytest.fixture
def mock_hook_json(mock_server_connection):
    """Return complete stdin JSON for a Scene.Update.Post hook where organized=true."""
    return {
        "server_connection": mock_server_connection,
        "args": {
            "hookContext": {
                "id": 42,
                "type": "Scene.Update.Post",
                "input": {"organized": True, "id": 42},
                "inputFields": ["organized", "id"],
            }
        },
    }


@pytest.fixture
def mock_task_json(mock_server_connection):
    """Return a factory function that creates stdin JSON for a given task mode."""

    def _factory(mode):
        return {
            "server_connection": mock_server_connection,
            "args": {"mode": mode},
        }

    return _factory


@pytest.fixture
def mock_stash_version():
    """Return a mock StashVersion object with version above minimum (0.28.0)."""
    version = MagicMock()
    version.major = 0
    version.minor = 28
    version.patch = 0
    version.__str__ = MagicMock(return_value="v0.28.0")
    return version


@pytest.fixture
def mock_stash_version_old():
    """Return a mock StashVersion object with version below minimum (0.20.0)."""
    version = MagicMock()
    version.major = 0
    version.minor = 20
    version.patch = 0
    version.__str__ = MagicMock(return_value="v0.20.0")
    return version


@pytest.fixture
def default_text_config():
    """Return a TextConfig instance with all defaults for text_processor tests."""
    return TextConfig()


@pytest.fixture
def make_text_config():
    """Return a factory that creates a TextConfig with keyword overrides.

    Usage:
        config = make_text_config(titlecase=True, use_ascii=True)
    """

    def _factory(**overrides):
        return replace(TextConfig(), **overrides)

    return _factory


@pytest.fixture
def make_filename_config():
    """Return a factory that creates a FilenameConfig with keyword overrides.

    Usage:
        config = make_filename_config(use_default=True, tag_templates={"JAV": "$title"})
    """

    def _factory(**overrides):
        return replace(FilenameConfig(), **overrides)

    return _factory


@pytest.fixture
def make_path_config():
    """Return a factory that creates a PathConfig with keyword overrides.

    Usage:
        config = make_path_config(use_default=True, path_templates={"/unsorted": "$performer"})
    """

    def _factory(**overrides):
        return replace(PathConfig(), **overrides)

    return _factory


@pytest.fixture
def make_formatting_config():
    """Return a factory that creates a FormattingConfig with keyword overrides.

    Usage:
        config = make_formatting_config(date_format="%d/%m/%Y")
    """

    def _factory(**overrides):
        return replace(FormattingConfig(), **overrides)

    return _factory


@pytest.fixture
def make_performer_config():
    """Return a factory that creates a PerformerConfig with keyword overrides.

    Usage:
        config = make_performer_config(sort="name", limit=5)
    """

    def _factory(**overrides):
        return replace(PerformerConfig(), **overrides)

    return _factory


@pytest.fixture
def make_studio_config():
    """Return a factory that creates a StudioConfig with keyword overrides.

    Usage:
        config = make_studio_config(squeeze_names=True, max_hierarchy_depth=3)
    """

    def _factory(**overrides):
        return replace(StudioConfig(), **overrides)

    return _factory


@pytest.fixture
def make_tag_config():
    """Return a factory that creates a TagConfig with keyword overrides.

    Usage:
        config = make_tag_config(whitelist=["HD"], separator=", ")
    """

    def _factory(**overrides):
        return replace(TagConfig(), **overrides)

    return _factory


@pytest.fixture
def full_scene():
    """Return a complete scene dict matching the Stash Scene Data Dict Reference.

    All fields are populated with realistic test values.
    """
    return {
        "id": "1234",
        "title": "Scene Title",
        "code": "ABC-123",
        "date": "2024-01-15",
        "rating100": 80,
        "organized": True,
        "stash_ids": [
            {"endpoint": "https://stashdb.org/graphql", "stash_id": "scene-uuid-123"}
        ],
        "files": [
            {
                "path": "/media/videos/scene.mp4",
                "basename": "scene.mp4",
                "video_codec": "h264",
                "audio_codec": "aac",
                "width": 1920,
                "height": 1080,
                "duration": 1800.5,
                "bit_rate": 5000000,
                "frame_rate": 29.97,
                "fingerprints": [
                    {"type": "oshash", "value": "abc123hash"},
                    {"type": "md5", "value": "def456md5"},
                    {"type": "phash", "value": "ghi789phash"},
                ],
            }
        ],
        "studio": {
            "id": "5",
            "name": "Studio Name",
            "parent_studio": {
                "id": "3",
                "name": "Parent Studio",
                "parent_studio": None,
            },
        },
        "tags": [
            {"id": "20", "name": "Tag One"},
            {"id": "21", "name": "Tag Two"},
            {"id": "22", "name": "Tag Three"},
        ],
        "performers": [
            {
                "id": "10",
                "name": "Performer Alpha",
                "gender": "FEMALE",
                "favorite": True,
                "rating100": 90,
                "stash_ids": [
                    {"endpoint": "https://stashdb.org/graphql", "stash_id": "perf-uuid-1"}
                ],
            },
            {
                "id": "11",
                "name": "Performer Beta",
                "gender": "MALE",
                "favorite": False,
                "rating100": 70,
                "stash_ids": [
                    {"endpoint": "https://stashdb.org/graphql", "stash_id": "perf-uuid-2"}
                ],
            },
        ],
        "groups": [
            {
                "group": {
                    "name": "Movie Title",
                    "date": "2024-01-01",
                },
                "scene_index": 3,
            }
        ],
    }


@pytest.fixture
def bare_scene():
    """Return a minimal scene dict with all optional fields None/empty.

    This is the bare-minimum scene that Stash would return.
    """
    return {
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
        "performers": [],
        "groups": [],
    }


# =============================================================================
# INTEGRATION TEST INFRASTRUCTURE
# =============================================================================


class MockStash:
    """Mock StashInterface that routes calls to pre-configured response data.

    Simulates the Stash GraphQL API without network access. Supports:
    - find_scene: returns scene data by ID from a scenes dict
    - find_scenes: returns scene lists (with pagination support)
    - move_files: records move operations instead of executing them
    - get_configuration: returns library paths config
    - find_plugin_config: returns plugin enabled/dry_run settings
    - stash_version: returns a configurable version object
    - find_tags: returns tags matching a filter
    - update_scene: records scene updates
    """

    def __init__(self):
        # Scene data store: {scene_id: scene_dict}
        self.scenes = {}
        # Library paths for get_configuration
        self.library_paths = ["/media/videos"]
        # Plugin config (enabled, dry_run)
        self.plugin_config = {"enabled": True, "dry_run": False}
        # Version string
        self._version_str = "0.28.0"
        # Recorded operations (for assertion)
        self.moves = []           # list of move_files call dicts
        self.scene_updates = []   # list of update_scene call dicts
        # Tags store: {tag_name: {"id": str, "name": str}}
        self.tags = {}

    def find_scene(self, scene_id, fragment=None):
        """Return scene data by ID, or None if not found."""
        return self.scenes.get(int(scene_id))

    def find_scenes(self, f=None, filter=None, fragment=None, get_count=False):
        """Return scene list, optionally filtered.

        Supports get_count=True for pagination count queries.
        Supports organized filter for backfill mode.
        """
        f = f or {}
        scenes = list(self.scenes.values())

        # Apply organized filter if present
        if "organized" in f:
            scenes = [s for s in scenes if s.get("organized") == f["organized"]]

        if get_count:
            return (len(scenes), [])

        # Pagination support
        if filter:
            page = filter.get("page", 1)
            per_page = filter.get("per_page", 100)
            if per_page == 0:
                return (len(scenes), [])
            start = (page - 1) * per_page
            end = start + per_page
            page_scenes = scenes[start:end]
            # Return id-only dicts when fragment is "id"
            if fragment == "id":
                return [{"id": str(s["id"])} for s in page_scenes]
            return page_scenes

        if fragment == "id":
            return [{"id": str(s["id"])} for s in scenes]
        return scenes

    def move_files(self, move_input):
        """Record a move operation instead of executing it."""
        self.moves.append(move_input)

    def get_configuration(self, fragment=None):
        """Return mock Stash configuration with library paths."""
        return {
            "general": {
                "stashes": [{"path": p} for p in self.library_paths]
            }
        }

    def find_plugin_config(self, plugin_id):
        """Return mock plugin config."""
        return self.plugin_config

    def configure_plugin(self, plugin_id, config):
        """Update mock plugin config."""
        self.plugin_config.update(config)

    def stash_version(self):
        """Return a mock version object."""
        v = MagicMock()
        parts = [int(x) for x in self._version_str.split(".")]
        v.major = parts[0]
        v.minor = parts[1]
        v.patch = parts[2]
        v.__str__ = MagicMock(return_value=f"v{self._version_str}")
        return v

    def find_tags(self, f=None):
        """Return tags matching a filter."""
        if f and "name" in f:
            name_filter = f["name"]
            target_name = name_filter.get("value", "")
            if target_name in self.tags:
                return [self.tags[target_name]]
        return []

    def update_scene(self, scene_input):
        """Record a scene update."""
        self.scene_updates.append(scene_input)


@pytest.fixture
def mock_stash_factory():
    """Return a factory function that creates configured MockStash instances.

    Usage:
        stash = mock_stash_factory(
            scenes={42: scene_dict},
            library_paths=["/media/videos"],
            dry_run=False,
        )
    """
    def _factory(
        scenes=None,
        library_paths=None,
        plugin_config=None,
        version_str="0.28.0",
        tags=None,
    ):
        ms = MockStash()
        if scenes:
            ms.scenes = {int(k): v for k, v in scenes.items()}
        if library_paths is not None:
            ms.library_paths = library_paths
        if plugin_config is not None:
            ms.plugin_config = plugin_config
        ms._version_str = version_str
        if tags:
            ms.tags = tags
        return ms

    return _factory


@pytest.fixture
def make_integration_scene():
    """Return a factory for building complete scene dicts with all fields populated.

    Produces scenes that work end-to-end through the full pipeline (metadata
    extraction, template resolution, text processing) without missing-field errors.

    Usage:
        scene = make_integration_scene(
            scene_id=42,
            title="My Scene",
            studio_name="StudioX",
            current_path="/media/videos/old_name.mp4",
            tags=[{"id": "10", "name": "Western"}],
            performers=[{"id": "1", "name": "Jane Doe", "gender": "FEMALE",
                         "favorite": False, "rating100": 80, "stash_ids": []}],
        )
    """
    def _factory(
        scene_id=42,
        title="Test Scene",
        code=None,
        date="2024-01-15",
        rating100=80,
        organized=True,
        current_path="/media/videos/old_name.mp4",
        studio_name="TestStudio",
        parent_studio_name=None,
        tags=None,
        performers=None,
        groups=None,
    ):
        studio = None
        if studio_name:
            studio = {
                "id": "5",
                "name": studio_name,
                "parent_studio": None,
            }
            if parent_studio_name:
                studio["parent_studio"] = {
                    "id": "3",
                    "name": parent_studio_name,
                    "parent_studio": None,
                }

        return {
            "id": str(scene_id),
            "title": title,
            "code": code,
            "date": date,
            "rating100": rating100,
            "organized": organized,
            "stash_ids": [],
            "files": [
                {
                    "id": "100",
                    "path": current_path,
                    "basename": os.path.basename(current_path),
                    "video_codec": "h264",
                    "audio_codec": "aac",
                    "width": 1920,
                    "height": 1080,
                    "duration": 1800.0,
                    "bit_rate": 5000000,
                    "frame_rate": 30.0,
                    "fingerprints": [],
                }
            ],
            "studio": studio,
            "tags": tags or [],
            "performers": performers or [],
            "groups": groups or [],
        }

    return _factory


@pytest.fixture
def make_integration_config():
    """Return a factory for building Config instances for integration tests.

    Creates real Config objects (not mocks) by merging overrides into DEFAULTS.
    This exercises the actual config loading path.

    Usage:
        config = make_integration_config(
            filename={"use_default": True, "default": "$date $title"},
            path={"use_default": True, "default": "/media/videos/$studio"},
        )
    """
    from config_loader import Config, DEFAULTS, deep_merge

    def _factory(**overrides):
        merged = deep_merge(DEFAULTS, overrides)
        return Config.from_dict(merged)

    return _factory
