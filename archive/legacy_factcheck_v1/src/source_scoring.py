try:
    from .factcheck.source_registry import classify_source, get_domain
except ImportError:
    from factcheck.source_registry import classify_source, get_domain


def source_reliability(url: str) -> float:
    return classify_source(url).trust
