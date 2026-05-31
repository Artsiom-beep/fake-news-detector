try:
    from .factcheck.cache import get_cache
except ImportError:
    from factcheck.cache import get_cache


def get(key: str):
    return get_cache().get("legacy", key)


def set_(key: str, value):
    get_cache().set("legacy", key, value)
