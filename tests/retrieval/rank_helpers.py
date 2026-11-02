"""A small realistic repository for ranking tests, and a helper that ranks an issue against it."""

from idx_helpers import index_of

from bugbite.retrieval import rank_files

CACHE = '''"""A small cache."""


class Cache:
    """A key value cache with a size limit."""

    def __init__(self, size):
        self.size = size

    def get(self, key):
        """Return the value for key."""
        return self.items.get(key)

    def set(self, key, value):
        self.items[key] = value

    def evict(self):
        """Remove the oldest item."""
        ...


class LRUCache(Cache):
    """Evicts the least recently used item."""

    def evict(self):
        ...
'''
TTL = '''"""Entries that expire."""
import time


class TTLCache:
    """A cache whose entries expire after a number of seconds."""

    def get(self, key):
        self.expire_entries()
        return self.items.get(key)

    def expire_entries(self):
        """Drop every entry older than its time to live."""
        now = time.time()
        for key in list(self.items):
            if now - self.times[key] > self.ttl:
                del self.items[key]
'''
KEYS = '''def make_key(*args, **kwargs):
    """Build a hashable key from call arguments."""
    return hash_args(args, tuple(sorted(kwargs.items())))


def hash_args(args, kwargs):
    return hash((args, kwargs))
'''
SERIALIZE = '''import json


def dumps(obj):
    """Encode a value as text."""
    return json.dumps(obj)


def loads(text):
    return json.loads(text)
'''
CONFIG = '''def load_config(path):
    """Read the configuration file."""
    return parse_config(open(path).read())


def parse_config(text):
    """Parse configuration text into a dict."""
    return {}
'''
TEST_CACHE = "from cachelib.cache import Cache\n\ndef test_evict():\n    ...\n\ndef test_get():\n    ...\n"
TEST_TTL = "from cachelib.ttl import TTLCache\n\ndef test_expire_entries():\n    ...\n"

FILES = {
    "src/cachelib/__init__.py": "", "src/cachelib/cache.py": CACHE, "src/cachelib/ttl.py": TTL, "src/cachelib/keys.py": KEYS,
    "src/cachelib/serialize.py": SERIALIZE, "src/cachelib/config.py": CONFIG, "src/cachelib/utils/timing.py": "def now():\n    return 0\n",
    "tests/conftest.py": "import pytest\n", "tests/test_cache.py": TEST_CACHE, "tests/test_ttl.py": TEST_TTL,
    "README.md": "# cachelib\n", "docs/guide.md": "How to use the cache.\n",
}


def fixture_index(tmp_path, files=None):
    return index_of(tmp_path, FILES if files is None else files)[0]


def ranked(tmp_path, issue, **kw):
    return rank_files(issue, fixture_index(tmp_path), **kw)


def paths(ranking):
    return [c.path for c in ranking.candidates]
