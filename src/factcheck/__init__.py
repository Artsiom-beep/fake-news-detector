from .config import PIPELINE_VERSION, PipelineConfig, build_config

__all__ = ["PIPELINE_VERSION", "PipelineConfig", "build_config", "run_factcheck"]


def run_factcheck(*args, **kwargs):
    from .service import run_factcheck as _run_factcheck

    return _run_factcheck(*args, **kwargs)
