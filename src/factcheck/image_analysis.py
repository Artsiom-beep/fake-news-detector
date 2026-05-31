from __future__ import annotations

import os
import re
import tempfile
from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
from typing import Any

from PIL import ExifTags, Image, ImageSequence, UnidentifiedImageError

from .config import build_config
from .schemas import FactCheckResult, FactCheckTrace, ImageAnalysisResult
from .service import run_factcheck

MAX_IMAGE_BYTES = 12 * 1024 * 1024
SUPPORTED_IMAGE_FORMATS = {"JPEG", "PNG", "WEBP", "BMP", "TIFF"}
SUPPORTED_TEMP_SUFFIXES = {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}
URL_PATTERN = re.compile(r"\b(?:https?://|www\.)[^\s<>()\"']+", re.I)
AI_METADATA_MARKERS = {
    "stable diffusion",
    "midjourney",
    "dall-e",
    "dalle",
    "comfyui",
    "automatic1111",
    "novelai",
    "leonardo ai",
    "firefly",
    "ideogram",
}
AI_FILENAME_MARKERS = {
    "ai-generated",
    "ai_generated",
    "chatgpt",
    "dall-e",
    "dalle",
    "generated_image",
    "imagefx",
    "midjourney",
    "stable-diffusion",
    "stable_diffusion",
}
ANDROID_EXPORTED_JPEG_PATTERN = re.compile(r"^jpeg_\d{8}_\d{6}[_-][a-z0-9-]+\.jpe?g$", re.I)
CAMERA_METADATA_KEYS = {"make", "model", "lensmodel", "datetimeoriginal", "focallength", "exposuretime"}
DISABLED_MODEL_VALUES = {"", "0", "false", "off", "disabled", "none", "metadata_only"}
MODEL_ONLY_AI_VERDICT_MODELS = {"haywoodsloan/ai-image-detector-deploy"}
MODEL_ONLY_AI_MIN_SCORE = 0.995
MODEL_ONLY_AI_MIN_MARGIN = 0.99

_AI_IMAGE_CLASSIFIER: Any | None = None
_AI_IMAGE_CLASSIFIER_NAME = ""


@dataclass(frozen=True)
class OCRLine:
    text: str
    confidence: float
    box: list[Any]


@dataclass(frozen=True)
class OCRResult:
    text: str
    confidence: float
    lines: list[OCRLine]
    detected_urls: list[str]
    warnings: list[str]


@dataclass(frozen=True)
class ImageModelSignal:
    ai_score: float | None
    real_score: float | None
    predicted_label: str
    margin: float
    reasons: list[str]
    warnings: list[str]


def _validate_image(image_bytes: bytes) -> Image.Image:
    if not image_bytes:
        raise ValueError("No image bytes were provided.")
    if len(image_bytes) > MAX_IMAGE_BYTES:
        raise ValueError("Image is too large. Maximum size is 12 MB.")
    try:
        image = Image.open(BytesIO(image_bytes))
    except (OSError, UnidentifiedImageError) as exc:
        raise ValueError("Unsupported or unreadable image file.") from exc
    if image.format not in SUPPORTED_IMAGE_FORMATS:
        raise ValueError(f"Unsupported image format: {image.format or 'unknown'}.")
    image.load()
    if getattr(image, "is_animated", False):
        image = next(ImageSequence.Iterator(image)).copy()
    return image.convert("RGB")


def _clean_ocr_text(text: str) -> str:
    text = re.sub(r"[ \t]+", " ", text or "")
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _ocr_bounds(line: OCRLine) -> tuple[float, float, float, float]:
    xs: list[float] = []
    ys: list[float] = []
    for point in line.box or []:
        if isinstance(point, (list, tuple)) and len(point) >= 2:
            try:
                xs.append(float(point[0]))
                ys.append(float(point[1]))
            except (TypeError, ValueError):
                pass
    if not xs or not ys:
        return 0.0, 0.0, 0.0, 0.0
    return min(xs), min(ys), max(xs), max(ys)


def _same_visual_row(first: OCRLine, second: OCRLine) -> bool:
    _first_left, first_top, _first_right, first_bottom = _ocr_bounds(first)
    _second_left, second_top, _second_right, second_bottom = _ocr_bounds(second)
    first_height = max(1.0, first_bottom - first_top)
    second_height = max(1.0, second_bottom - second_top)
    overlap = min(first_bottom, second_bottom) - max(first_top, second_top)
    if overlap >= 0.45 * min(first_height, second_height):
        return True
    first_center = (first_top + first_bottom) / 2.0
    second_center = (second_top + second_bottom) / 2.0
    return abs(first_center - second_center) <= 0.45 * max(first_height, second_height)


def _join_ocr_lines_in_reading_order(lines: list[OCRLine]) -> str:
    if not lines:
        return ""

    sorted_lines = sorted(
        lines,
        key=lambda line: ((_ocr_bounds(line)[1] + _ocr_bounds(line)[3]) / 2.0, _ocr_bounds(line)[0]),
    )
    rows: list[list[OCRLine]] = []
    for line in sorted_lines:
        if rows and any(_same_visual_row(existing, line) for existing in rows[-1]):
            rows[-1].append(line)
        else:
            rows.append([line])

    row_texts = []
    for row in rows:
        row.sort(key=lambda line: _ocr_bounds(line)[0])
        row_text = " ".join(line.text.strip() for line in row if line.text.strip())
        if row_text:
            row_texts.append(row_text)
    return _clean_ocr_text("\n".join(row_texts))


def _detected_urls(text: str) -> list[str]:
    urls = []
    seen = set()
    for match in URL_PATTERN.findall(text or ""):
        url = match.rstrip(".,;:)]}")
        if url.lower().startswith("www."):
            url = f"https://{url}"
        key = url.lower()
        if key not in seen:
            seen.add(key)
            urls.append(url)
    return urls


def extract_ocr_text(image_bytes: bytes, filename: str = "") -> OCRResult:
    image = _validate_image(image_bytes)
    suffix = (Path(filename or "upload.png").suffix or ".png").lower()
    if suffix not in SUPPORTED_TEMP_SUFFIXES:
        suffix = ".png"
    lines: list[OCRLine] = []
    warnings: list[str] = []

    try:
        from rapidocr_onnxruntime import RapidOCR
    except Exception as exc:
        return OCRResult(
            text="",
            confidence=0.0,
            lines=[],
            detected_urls=[],
            warnings=[f"ocr_dependency_unavailable:{type(exc).__name__}"],
        )

    with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temp:
        temp_path = temp.name
    try:
        image.save(temp_path)
        engine = RapidOCR()
        result, _elapsed = engine(temp_path)
    finally:
        try:
            os.remove(temp_path)
        except OSError:
            pass

    for item in result or []:
        if len(item) < 3:
            continue
        box, text, confidence = item[0], str(item[1]).strip(), float(item[2] or 0.0)
        if text:
            lines.append(OCRLine(text=text, confidence=confidence, box=box))

    if not lines:
        warnings.append("ocr_no_text_detected")
    joined = _join_ocr_lines_in_reading_order(lines)
    confidence = sum(line.confidence for line in lines) / max(len(lines), 1)
    return OCRResult(
        text=joined,
        confidence=confidence,
        lines=lines,
        detected_urls=_detected_urls(joined),
        warnings=warnings,
    )


def _metadata_dict(image: Image.Image) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": image.format or "",
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
    }
    for key, value in (image.info or {}).items():
        if isinstance(value, (str, int, float, bool)):
            metadata[str(key).lower()] = value

    try:
        exif = image.getexif()
        for tag_id, value in exif.items():
            key = str(ExifTags.TAGS.get(tag_id, tag_id)).lower()
            if isinstance(value, (str, int, float, bool)):
                metadata[key] = value
    except Exception:
        pass
    return metadata


def _image_stat_features(image: Image.Image) -> dict[str, float]:
    import numpy as np

    small = image.convert("RGB").resize((128, 128))
    arr = np.asarray(small).astype("float32") / 255.0
    gray = arr.mean(axis=2)
    color_std = float(arr.std())
    edge_density = float((abs(np.diff(gray, axis=0)).mean() + abs(np.diff(gray, axis=1)).mean()) / 2.0)
    hist, _ = np.histogram((gray * 255).astype("uint8"), bins=64, range=(0, 255), density=True)
    hist = hist[hist > 0]
    entropy = float(-(hist * np.log2(hist)).sum() / 6.0) if len(hist) else 0.0
    return {
        "color_std": round(color_std, 4),
        "edge_density": round(edge_density, 4),
        "entropy": round(max(0.0, min(1.0, entropy)), 4),
    }


def _optional_ai_model_signal(image: Image.Image) -> ImageModelSignal:
    global _AI_IMAGE_CLASSIFIER, _AI_IMAGE_CLASSIFIER_NAME
    model_name = os.getenv("FACTCHECK_AI_IMAGE_MODEL", "").strip()
    if model_name.lower() in DISABLED_MODEL_VALUES:
        return ImageModelSignal(
            ai_score=None,
            real_score=None,
            predicted_label="disabled",
            margin=0.0,
            reasons=["optional_ai_image_model_disabled"],
            warnings=[],
        )
    try:
        from transformers import pipeline

        if _AI_IMAGE_CLASSIFIER is None or _AI_IMAGE_CLASSIFIER_NAME != model_name:
            _AI_IMAGE_CLASSIFIER = pipeline("image-classification", model=model_name)
            _AI_IMAGE_CLASSIFIER_NAME = model_name
        classifier = _AI_IMAGE_CLASSIFIER
        outputs = classifier(image)
    except Exception as exc:
        return ImageModelSignal(
            ai_score=None,
            real_score=None,
            predicted_label="failed",
            margin=0.0,
            reasons=[],
            warnings=[f"optional_ai_image_model_failed:{type(exc).__name__}"],
        )

    ai_score: float | None = None
    real_score: float | None = None
    reasons: list[str] = []
    for item in outputs or []:
        label = str(item.get("label", "")).lower()
        score = float(item.get("score", 0.0))
        if any(marker in label for marker in ["ai", "generated", "synthetic", "fake", "artificial"]):
            ai_score = score if ai_score is None else max(ai_score, score)
            reasons.append(f"model_ai_label={label}:{score:.3f}")
        if any(marker in label for marker in ["real", "camera", "natural", "human", "authentic"]):
            real_score = score if real_score is None else max(real_score, score)
            reasons.append(f"model_real_label={label}:{score:.3f}")

    ai_value = ai_score or 0.0
    real_value = real_score or 0.0
    if ai_score is None and real_score is None:
        return ImageModelSignal(
            ai_score=None,
            real_score=None,
            predicted_label="unknown",
            margin=0.0,
            reasons=reasons or ["optional_ai_image_model_no_mapped_label"],
            warnings=["optional_ai_image_model_no_mapped_label"],
        )

    if ai_value > real_value:
        predicted_label = "fake"
    elif real_value > ai_value:
        predicted_label = "real"
    else:
        predicted_label = "ambiguous"
    margin = abs(ai_value - real_value)
    reasons.extend(
        [
            f"model_prediction={predicted_label}",
            f"model_margin={margin:.3f}",
        ]
    )
    return ImageModelSignal(
        ai_score=ai_score,
        real_score=real_score,
        predicted_label=predicted_label,
        margin=margin,
        reasons=reasons,
        warnings=[],
    )


def detect_ai_image(image_bytes: bytes, filename: str = "") -> ImageAnalysisResult:
    image = _validate_image(image_bytes)
    raw_image = Image.open(BytesIO(image_bytes))
    raw_image.load()
    metadata = _metadata_dict(raw_image)
    metadata.update(_image_stat_features(image))
    metadata_text = " ".join(str(value).lower() for value in metadata.values())
    filename_text = Path(filename or "").name.lower()

    reasons: list[str] = []
    warnings: list[str] = []
    score = 0.18

    matched_markers = [marker for marker in AI_METADATA_MARKERS if marker in metadata_text]
    filename_markers = [marker for marker in AI_FILENAME_MARKERS if marker in filename_text]
    weak_ai_signals = 0
    if matched_markers:
        score = max(score, 0.9)
        reasons.append(f"ai_metadata_marker={','.join(sorted(matched_markers))}")
    if filename_markers:
        score = max(score, 0.84)
        reasons.append(f"ai_filename_marker={','.join(sorted(filename_markers))}")

    metadata_keys = {str(key).lower() for key in metadata}
    camera_keys = metadata_keys & CAMERA_METADATA_KEYS
    if camera_keys:
        score = max(0.0, score - 0.14)
        reasons.append(f"camera_metadata_present={','.join(sorted(camera_keys))}")
    else:
        score += 0.08
        warnings.append("camera_metadata_missing_not_proof")
        if ANDROID_EXPORTED_JPEG_PATTERN.match(filename_text):
            score = max(score + 0.04, 0.32)
            weak_ai_signals += 1
            reasons.append("android_exported_jpeg_without_camera_metadata")
            warnings.append("image_may_be_exported_or_shared_not_original_camera")

    width = int(metadata.get("width", 0) or 0)
    height = int(metadata.get("height", 0) or 0)
    if width == height and width in {512, 768, 1024, 1536, 2048}:
        score += 0.08
        weak_ai_signals += 1
        reasons.append(f"common_square_ai_dimension={width}x{height}")
    elif (
        width >= 512
        and height >= 512
        and width <= 2048
        and height <= 2048
        and width % 64 == 0
        and height % 64 == 0
    ):
        score += 0.05
        weak_ai_signals += 1
        reasons.append(f"generator_friendly_dimensions={width}x{height}")

    entropy = float(metadata.get("entropy", 0.0) or 0.0)
    edge_density = float(metadata.get("edge_density", 0.0) or 0.0)
    if entropy > 0.88 and edge_density < 0.08:
        score += 0.06
        weak_ai_signals += 1
        reasons.append("smooth_high_entropy_pattern")

    model_signal = _optional_ai_model_signal(image)
    reasons.extend(model_signal.reasons)
    warnings.extend(model_signal.warnings)
    model_ai = model_signal.ai_score or 0.0
    model_real = model_signal.real_score or 0.0
    model_name = os.getenv("FACTCHECK_AI_IMAGE_MODEL", "").strip().lower()
    model_only_ai_allowed = model_name in MODEL_ONLY_AI_VERDICT_MODELS
    strong_ai_model = (
        model_only_ai_allowed
        and model_ai >= MODEL_ONLY_AI_MIN_SCORE
        and model_signal.margin >= MODEL_ONLY_AI_MIN_MARGIN
    )
    suspicious_ai_model = model_ai >= 0.90 and model_signal.margin >= 0.45
    strong_real_model = model_real >= 0.80 and model_signal.margin >= 0.35
    if model_signal.ai_score is not None or model_signal.real_score is not None:
        if matched_markers:
            score = max(score, 0.9 + 0.1 * model_ai)
        elif strong_ai_model:
            score = max(score, 0.80 + 0.08 * min(1.0, (model_ai - MODEL_ONLY_AI_MIN_SCORE) / 0.005))
            reasons.append("model_strong_ai_signal")
        elif suspicious_ai_model:
            score = max(score, 0.65 + 0.07 * min(1.0, (model_ai - 0.90) / 0.10))
            reasons.append("model_strong_ai_signal")
            warnings.append("model_strong_ai_signal_not_enough_without_metadata")
        elif strong_real_model:
            score = min(score, 0.30 - 0.20 * min(1.0, (model_real - 0.80) / 0.20))
            reasons.append("model_strong_real_signal")
        elif model_ai >= 0.55:
            score = max(score, min(0.65, 0.40 + 0.25 * ((model_ai - 0.55) / 0.35)))
            reasons.append("model_ambiguous_not_decisive")
            warnings.append("model_ambiguous_not_decisive")
        elif model_ai > 0.0 and not matched_markers:
            score = min(score, 0.30)

    if model_signal.predicted_label == "disabled" and weak_ai_signals >= 2 and not camera_keys:
        score = max(score, 0.40)
        warnings.append("limited_metadata_only_ai_check")

    if matched_markers or filename_markers:
        score = max(score, 0.90)

    score = max(0.0, min(1.0, score))
    if matched_markers or filename_markers or strong_ai_model:
        label = "likely_ai"
    elif strong_real_model:
        label = "likely_not_ai"
    else:
        label = "uncertain"
        warnings.append("ai_image_detection_not_definitive")

    return ImageAnalysisResult(
        mode="ai_image_detection",
        ai_generated_score=score,
        ai_label=label,
        warnings=warnings,
        reasons=reasons,
        metadata=metadata,
    )


def _looks_like_assertive_question_claim(question: str) -> bool:
    cleaned = re.sub(r"\s+", " ", (question or "").strip())
    if not cleaned or cleaned.endswith("?"):
        return False
    tokens = re.findall(r"[A-Za-z0-9]+", cleaned)
    if len(tokens) < 3:
        return False
    return bool(
        re.search(
            r"\b(?:is|are|was|were|has|have|had|will|does|do|did|causes?|cures?|includes?|orbits?|prevents?|treats?)\b",
            cleaned,
            flags=re.I,
        )
    )


def _select_screenshot_factcheck_text(ocr_text: str, question: str) -> tuple[str, str]:
    question = re.sub(r"\s+", " ", (question or "").strip())
    if _looks_like_assertive_question_claim(question):
        return question.strip(" ."), "screenshot_question_claim_used"
    return ocr_text, "screenshot_ocr_text_used"


def run_screenshot_factcheck(
    image_bytes: bytes,
    filename: str = "",
    question: str = "",
) -> FactCheckResult:
    ocr = extract_ocr_text(image_bytes, filename=filename)
    analysis = ImageAnalysisResult(
        mode="screenshot_ocr",
        ocr_text=ocr.text,
        ocr_confidence=ocr.confidence,
        detected_urls=ocr.detected_urls,
        warnings=list(ocr.warnings),
        reasons=[f"ocr_lines={len(ocr.lines)}"],
    )

    if not ocr.text or len(re.findall(r"\w+", ocr.text)) < 3:
        config = build_config()
        trace = FactCheckTrace(mode="best_accuracy")
        trace.fallbacks_used.extend(["image_ocr_no_checkable_text", *ocr.warnings])
        return FactCheckResult(
            verdict="uncertain",
            confidence=0.2,
            summary=(
                "No readable claim was found in the image. This version can check text in screenshots, "
                "but it cannot prove the authenticity of a photo without text."
            ),
            claim=question.strip(),
            evidence=[],
            trace=trace,
            claims=[],
            config=config.snapshot(),
            pipeline_version=config.pipeline_version,
            image_analysis=analysis,
        )

    factcheck_text, input_reason = _select_screenshot_factcheck_text(ocr.text, question)
    detected_url = ocr.detected_urls[0] if ocr.detected_urls and input_reason == "screenshot_ocr_text_used" else ""
    result = run_factcheck(text=factcheck_text, url=detected_url)
    result.image_analysis = analysis
    result.trace.fallbacks_used.append(input_reason)
    result.trace.fallbacks_used.extend(ocr.warnings)
    return result


def run_ai_image_check(
    image_bytes: bytes,
    filename: str = "",
    question: str = "",
) -> FactCheckResult:
    analysis = detect_ai_image(image_bytes, filename=filename)
    config = build_config()
    trace = FactCheckTrace(mode="best_accuracy")
    trace.decision_reasons.extend(analysis.reasons)
    trace.fallbacks_used.extend(analysis.warnings)
    label = analysis.ai_label
    if label == "likely_ai":
        summary = "The image has strong AI-generation signals. Treat it as likely AI-generated unless an original source proves otherwise."
        confidence = max(0.55, min(0.82, analysis.ai_generated_score))
    elif label == "likely_not_ai":
        summary = "The image has low AI-generation risk based on available metadata, but this is not proof that it is authentic."
        confidence = 0.55
    else:
        if analysis.ai_generated_score >= 0.65:
            summary = (
                "The image has some AI or non-original-file signals, but not enough evidence "
                "for a likely AI verdict."
            )
        else:
            summary = (
                "The lightweight cloud check found no strong AI markers. This does not prove "
                "that the image is real."
            )
        confidence = 0.34

    return FactCheckResult(
        verdict="uncertain",
        confidence=confidence,
        summary=summary,
        claim=question.strip() or (filename or "Uploaded image"),
        evidence=[],
        trace=trace,
        claims=[],
        config=config.snapshot(),
        pipeline_version=config.pipeline_version,
        image_analysis=analysis,
    )
