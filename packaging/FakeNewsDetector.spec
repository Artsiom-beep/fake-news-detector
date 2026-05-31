# -*- mode: python ; coding: utf-8 -*-

from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files, collect_submodules, copy_metadata


ROOT = Path(SPECPATH).resolve().parent
ICON_PATH = ROOT / "build" / "icon" / "FakeNewsDetector.ico"


def safe_collect_data(package_name):
    try:
        return collect_data_files(package_name)
    except Exception:
        return []


def safe_collect_submodules(package_name):
    try:
        return collect_submodules(package_name)
    except Exception:
        return []


def safe_copy_metadata(package_name):
    try:
        return copy_metadata(package_name)
    except Exception:
        return []


datas = []
for relative_path in [
    "data/factcheck/common_knowledge_v1.json",
    "data/factcheck/seed_evidence.jsonl",
]:
    source = ROOT / relative_path
    if source.exists():
        datas.append((str(source), str(Path(relative_path).parent)))

for package_name in [
    "rapidocr_onnxruntime",
    "onnxruntime",
    "cv2",
    "PIL",
]:
    datas += safe_collect_data(package_name)

for package_name in [
    "fastapi",
    "starlette",
    "pydantic",
    "uvicorn",
    "pywebview",
    "rapidocr-onnxruntime",
    "onnxruntime",
]:
    datas += safe_copy_metadata(package_name)

hiddenimports = sorted(
    set(
        [
            "src.ui",
            "src.factcheck.claim_prior",
            "src.factcheck.claims",
            "src.factcheck.cache",
            "src.factcheck.common_knowledge",
            "src.factcheck.config",
            "src.factcheck.decision",
            "src.factcheck.domain_parsers",
            "src.factcheck.evidence",
            "src.factcheck.image_analysis",
            "src.factcheck.ingest",
            "src.factcheck.knowledge_sources",
            "src.factcheck.news_credibility",
            "src.factcheck.retrieval",
            "src.factcheck.schemas",
            "src.factcheck.service",
            "src.factcheck.source_registry",
            "src.nli",
            "uvicorn.loops.auto",
            "uvicorn.protocols.http.auto",
            "uvicorn.protocols.websockets.auto",
            "webview",
        ]
        + safe_collect_submodules("webview")
        + safe_collect_submodules("rapidocr_onnxruntime")
    )
)

excludes = [
    "accelerate",
    "datasets",
    "huggingface_hub",
    "pandas",
    "pyarrow",
    "safetensors",
    "sentencepiece",
    "sklearn",
    "tensorflow",
    "tokenizers",
    "torch",
    "torchvision",
    "transformers",
]

a = Analysis(
    [str(ROOT / "src" / "desktop_app.py")],
    pathex=[str(ROOT)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=excludes,
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="FakeNewsDetector",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    icon=str(ICON_PATH) if ICON_PATH.exists() else None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="FakeNewsDetector",
)
