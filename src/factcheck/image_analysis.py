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
    '"model"',
    '"prompt"',
    "actualmodel",
    "ai-generated",
    "ai generated",
    "automatic1111",
    "chatgpt",
    "completionimagetokens",
    "comfyui",
    "dall-e",
    "dalle",
    "firefly",
    "generated image",
    "ideogram",
    "image generator",
    "imagefx",
    "leonardo ai",
    "stable diffusion",
    "midjourney",
    "negative_prompt",
    "novelai",
    "openai",
    "originalprompt",
    "pollinations",
    "sana",
    "seed",
    "stable-diffusion",
    "trackingdata",
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


CONTEXT_STRING_KEYS = {
    "source",
    "filename",
    "displayName",
    "mimeType",
    "relativePath",
    "bucketName",
    "uriAuthority",
    "extension",
}
CONTEXT_INT_KEYS = {
    "mediaStoreId",
    "dateTaken",
    "dateAdded",
    "sizeBytes",
    "width",
    "height",
}
CONTEXT_BOOL_KEYS = {"usedOriginalUri"}
ANDROID_CAMERA_SOURCES = {"latest_camera", "camera_original_list", "matched_camera_original"}


def _safe_image_context(image_context: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(image_context, dict):
        return {}
    safe: dict[str, Any] = {}
    for key in CONTEXT_STRING_KEYS:
        value = image_context.get(key)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            safe[key] = text[:180]
    for key in CONTEXT_INT_KEYS:
        value = image_context.get(key)
        try:
            number = int(value)
        except (TypeError, ValueError):
            continue
        if number >= 0:
            safe[key] = number
    for key in CONTEXT_BOOL_KEYS:
        value = image_context.get(key)
        if isinstance(value, bool):
            safe[key] = value
        elif isinstance(value, (int, float)):
            safe[key] = bool(value)
        elif isinstance(value, str):
            safe[key] = value.strip().lower() in {"1", "true", "yes"}
    return safe


def _context_int(context: dict[str, Any], key: str) -> int:
    value = context.get(key)
    return value if isinstance(value, int) else 0


def _camera_context_signal(context: dict[str, Any]) -> tuple[bool, list[str], list[str]]:
    if not context:
        return False, [], []
    source = str(context.get("source", "")).strip().lower()
    relative_path = str(context.get("relativePath", "")).replace("\\", "/").lower()
    bucket_name = str(context.get("bucketName", "")).strip().lower()
    uri_authority = str(context.get("uriAuthority", "")).strip().lower()
    width = _context_int(context, "width")
    height = _context_int(context, "height")
    size_bytes = _context_int(context, "sizeBytes")
    date_taken = _context_int(context, "dateTaken")
    date_added = _context_int(context, "dateAdded")
    used_original_uri = bool(context.get("usedOriginalUri"))

    source_is_camera = source in ANDROID_CAMERA_SOURCES
    path_is_camera = "dcim/camera" in relative_path or bucket_name in {"camera", "camera roll", "cameraroll"}
    media_store_source = "media" in uri_authority or source_is_camera
    has_date = date_taken > 0 or date_added > 0
    has_dimensions = width > 0 and height > 0
    has_file_size = size_bytes > 0

    reasons: list[str] = []
    warnings: list[str] = []
    strength = 0
    if source_is_camera:
        strength += 2
        reasons.append("android_camera_library_context")
        reasons.append(f"android_camera_source={source}")
    if path_is_camera:
        strength += 2
        if "android_camera_library_context" not in reasons:
            reasons.append("android_camera_library_context")
        reasons.append("android_camera_path=dcim_camera")
    if used_original_uri:
        strength += 1
        reasons.append("media_store_original_uri_used")
    if has_date:
        strength += 1
        reasons.append("media_store_date_taken_present")
    if has_dimensions:
        strength += 1
        reasons.append(f"media_store_dimensions={width}x{height}")
    if has_file_size:
        strength += 1
    if media_store_source:
        strength += 1

    strong = (source_is_camera or path_is_camera) and strength >= 4
    if strong:
        warnings.append("camera_context_not_proof")
    elif context:
        warnings.append("metadata_context_not_camera_origin")
    return strong, reasons, warnings


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


def _metadata_value(value: Any) -> str | int | float | bool | None:
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, bytes):
        for encoding in ("utf-8", "latin-1"):
            try:
                text = value.decode(encoding, errors="ignore")
                text = text.replace("\x00", " ").strip()
                if text:
                    return text[:4000]
            except Exception:
                continue
    return None


def _metadata_dict(image: Image.Image) -> dict[str, Any]:
    metadata: dict[str, Any] = {
        "format": image.format or "",
        "width": image.width,
        "height": image.height,
        "mode": image.mode,
    }
    for key, value in (image.info or {}).items():
        safe_value = _metadata_value(value)
        if safe_value is not None:
            metadata[str(key).lower()] = safe_value

    try:
        exif = image.getexif()
        for tag_id, value in exif.items():
            key = str(ExifTags.TAGS.get(tag_id, tag_id)).lower()
            safe_value = _metadata_value(value)
            if safe_value is not None:
                metadata[key] = safe_value
    except Exception:
        pass
    return metadata


def _image_stat_features(image: Image.Image) -> dict[str, float]:
    import numpy as np

    small = image.convert("RGB").resize((256, 256))
    arr = np.asarray(small).astype("float32") / 255.0
    gray = arr.mean(axis=2)
    color_std = float(arr.std())
    edge_density = float((abs(np.diff(gray, axis=0)).mean() + abs(np.diff(gray, axis=1)).mean()) / 2.0)
    hist, _ = np.histogram((gray * 255).astype("uint8"), bins=64, range=(0, 255), density=True)
    hist = hist[hist > 0]
    entropy = float(-(hist * np.log2(hist)).sum() / 6.0) if len(hist) else 0.0

    laplacian = np.zeros_like(gray)
    laplacian[1:-1, 1:-1] = (
        -4.0 * gray[1:-1, 1:-1]
        + gray[:-2, 1:-1]
        + gray[2:, 1:-1]
        + gray[1:-1, :-2]
        + gray[1:-1, 2:]
    )
    laplacian_var = float(laplacian.var())

    vertical_diffs = np.abs(np.diff(gray, axis=1))
    horizontal_diffs = np.abs(np.diff(gray, axis=0))
    vertical_boundary = vertical_diffs[:, 7::8].mean() if vertical_diffs[:, 7::8].size else 0.0
    horizontal_boundary = horizontal_diffs[7::8, :].mean() if horizontal_diffs[7::8, :].size else 0.0
    vertical_internal = (
        np.delete(vertical_diffs, np.arange(7, vertical_diffs.shape[1], 8), axis=1).mean()
        if vertical_diffs.shape[1] > 1
        else 0.0
    )
    horizontal_internal = (
        np.delete(horizontal_diffs, np.arange(7, horizontal_diffs.shape[0], 8), axis=0).mean()
        if horizontal_diffs.shape[0] > 1
        else 0.0
    )
    block_boundary_ratio = float(
        ((vertical_boundary + horizontal_boundary) / 2.0)
        / (((vertical_internal + horizontal_internal) / 2.0) + 1e-6)
    )

    channel_max = arr.max(axis=2)
    channel_min = arr.min(axis=2)
    saturation = (channel_max - channel_min) / (channel_max + 1e-6)
    flat = arr.reshape(-1, 3)
    try:
        if float(flat.std(axis=0).min()) <= 1e-6:
            channel_corr = 0.0
        else:
            corr = np.corrcoef(flat.T)
            channel_corr = float((corr[0, 1] + corr[0, 2] + corr[1, 2]) / 3.0)
            if not np.isfinite(channel_corr):
                channel_corr = 0.0
    except Exception:
        channel_corr = 0.0

    from PIL import ImageFilter

    blurred = np.asarray(small.filter(ImageFilter.GaussianBlur(radius=1.2))).astype("float32") / 255.0
    residual = arr - blurred
    patch_luma = gray.reshape(32, 8, 32, 8).mean(axis=(1, 3))
    return {
        "color_std": round(color_std, 4),
        "edge_density": round(edge_density, 4),
        "entropy": round(max(0.0, min(1.0, entropy)), 4),
        "laplacian_var": round(max(0.0, laplacian_var), 5),
        "jpeg_block_boundary_ratio": round(max(0.0, block_boundary_ratio), 4),
        "saturation_mean": round(float(saturation.mean()), 4),
        "saturation_std": round(float(saturation.std()), 4),
        "channel_correlation": round(max(-1.0, min(1.0, channel_corr)), 4),
        "high_frequency_residual_std": round(float(residual.std()), 4),
        "high_frequency_residual_mean": round(float(np.abs(residual).mean()), 4),
        "patch_luma_std": round(float(patch_luma.std()), 4),
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


def detect_ai_image(
    image_bytes: bytes,
    filename: str = "",
    image_context: dict[str, Any] | None = None,
) -> ImageAnalysisResult:
    image = _validate_image(image_bytes)
    raw_image = Image.open(BytesIO(image_bytes))
    raw_image.load()
    metadata = _metadata_dict(raw_image)
    metadata.update(_image_stat_features(image))
    safe_context = _safe_image_context(image_context)
    camera_context_strong, context_reasons, context_warnings = _camera_context_signal(safe_context)
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
        if context_reasons:
            reasons.extend(context_reasons)
        warnings.extend(context_warnings)
    elif camera_context_strong:
        score = max(0.0, score - 0.10)
        reasons.extend(context_reasons)
        warnings.extend(context_warnings)
    else:
        score += 0.08
        warnings.append("camera_metadata_missing_not_proof")
        if ANDROID_EXPORTED_JPEG_PATTERN.match(filename_text):
            score = max(score + 0.04, 0.32)
            weak_ai_signals += 1
            reasons.append("android_exported_jpeg_without_camera_metadata")
            warnings.append("image_may_be_exported_or_shared_not_original_camera")
        warnings.extend(context_warnings)

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

    visual_ai_points = 0.0
    visual_ai_reasons: list[str] = []
    visual_real_points = 0.0
    visual_real_reasons: list[str] = []
    laplacian_var = float(metadata.get("laplacian_var", 0.0) or 0.0)
    residual_std = float(metadata.get("high_frequency_residual_std", 0.0) or 0.0)
    residual_mean = float(metadata.get("high_frequency_residual_mean", 0.0) or 0.0)
    patch_luma_std = float(metadata.get("patch_luma_std", 0.0) or 0.0)
    saturation_mean = float(metadata.get("saturation_mean", 0.0) or 0.0)
    saturation_std = float(metadata.get("saturation_std", 0.0) or 0.0)
    channel_correlation = float(metadata.get("channel_correlation", 0.0) or 0.0)
    block_boundary_ratio = float(metadata.get("jpeg_block_boundary_ratio", 0.0) or 0.0)
    progressive_jpeg = bool(metadata.get("progressive")) or bool(metadata.get("progression"))
    complex_enough_for_visual_check = entropy >= 0.20 and patch_luma_std >= 0.045
    camera_origin_signal = bool(camera_keys or camera_context_strong)

    if not camera_origin_signal and complex_enough_for_visual_check:
        if width >= 512 and height >= 512 and width % 64 == 0 and height % 64 == 0:
            visual_ai_points += 0.16
            visual_ai_reasons.append("visual_generator_canvas_size")
            if edge_density <= 0.012 and laplacian_var <= 0.006 and residual_std <= 0.012:
                visual_ai_points += 0.12
                visual_ai_reasons.append("visual_over_smooth_generated_canvas")
        if 0.010 <= residual_std <= 0.040 and edge_density <= 0.036 and laplacian_var <= 0.018:
            visual_ai_points += 0.18
            visual_ai_reasons.append("visual_low_sensor_noise_smooth_detail")
        if 0.006 <= residual_mean <= 0.024 and 0.09 <= patch_luma_std <= 0.36:
            visual_ai_points += 0.08
            visual_ai_reasons.append("visual_even_high_frequency_residual")
        if channel_correlation >= 0.92 and saturation_mean <= 0.38 and saturation_std <= 0.30:
            visual_ai_points += 0.07
            visual_ai_reasons.append("visual_tightly_correlated_color_channels")
        if 0.94 <= block_boundary_ratio <= 1.08 and not progressive_jpeg:
            visual_ai_points += 0.06
            visual_ai_reasons.append("visual_single_pass_compression_pattern")

    if not camera_origin_signal:
        if residual_std >= 0.046 or laplacian_var >= 0.026:
            visual_real_points += 0.12
            visual_real_reasons.append("visual_camera_like_texture")
        if progressive_jpeg:
            visual_real_points += 0.05
            visual_real_reasons.append("visual_web_photo_progressive_jpeg")
        if patch_luma_std < 0.045 and entropy < 0.35:
            visual_real_points += 0.08
            visual_real_reasons.append("visual_too_plain_for_ai_verdict")

    visual_score = max(0.0, visual_ai_points - visual_real_points)
    if visual_ai_reasons:
        reasons.extend(visual_ai_reasons)
        metadata["visual_ai_points"] = round(visual_ai_points, 3)
        metadata["visual_real_points"] = round(visual_real_points, 3)
    if visual_real_reasons:
        reasons.extend(visual_real_reasons)
    strong_visual_ai = visual_score >= 0.34 and not camera_origin_signal
    possible_visual_ai = visual_score >= 0.22 and not camera_origin_signal
    if strong_visual_ai:
        score = max(score, min(0.78, 0.50 + visual_score))
        reasons.append("visual_forensic_ai_signal")
    elif possible_visual_ai:
        score = max(score, min(0.64, 0.38 + visual_score))
        reasons.append("visual_forensic_weak_ai_signal")
        warnings.append("visual_forensic_signal_not_definitive")
    elif visual_real_points >= 0.12 and not camera_origin_signal:
        score = min(score, 0.30)

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

    if model_signal.predicted_label == "disabled" and (weak_ai_signals >= 2 or possible_visual_ai) and not camera_keys:
        score = max(score, 0.40)
        warnings.append("lightweight_visual_ai_check")

    if matched_markers or filename_markers:
        score = max(score, 0.90)
    elif camera_context_strong and not strong_ai_model and not suspicious_ai_model:
        score = min(score, 0.24)

    score = max(0.0, min(1.0, score))
    if matched_markers or filename_markers or strong_ai_model or strong_visual_ai:
        label = "likely_ai"
    elif strong_real_model or (camera_context_strong and not suspicious_ai_model):
        label = "likely_not_ai"
    else:
        label = "uncertain"
        warnings.append("ai_image_detection_not_definitive")
    if safe_context:
        metadata["selection_context"] = safe_context

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
    image_context: dict[str, Any] | None = None,
) -> FactCheckResult:
    analysis = detect_ai_image(image_bytes, filename=filename, image_context=image_context)
    config = build_config()
    trace = FactCheckTrace(mode="best_accuracy")
    trace.decision_reasons.extend(analysis.reasons)
    trace.fallbacks_used.extend(analysis.warnings)
    label = analysis.ai_label
    has_ai_metadata = any(reason.startswith("ai_metadata_marker=") for reason in analysis.reasons)
    has_ai_filename = any(reason.startswith("ai_filename_marker=") for reason in analysis.reasons)
    has_camera_metadata = any(reason.startswith("camera_metadata_present=") for reason in analysis.reasons)
    has_camera_context = "android_camera_library_context" in analysis.reasons
    has_visual_ai = "visual_forensic_ai_signal" in analysis.reasons
    has_weak_visual_ai = "visual_forensic_weak_ai_signal" in analysis.reasons
    metadata_missing = "camera_metadata_missing_not_proof" in analysis.warnings
    if has_ai_metadata:
        summary = (
            "AI-generator metadata was found in the image file. This is a strong metadata clue, "
            "although metadata can be edited."
        )
        confidence = max(0.55, min(0.82, analysis.ai_generated_score))
    elif has_ai_filename:
        summary = (
            "The filename contains an AI-generator clue. This is useful metadata context, "
            "but it is not proof by itself."
        )
        confidence = max(0.50, min(0.72, analysis.ai_generated_score))
    elif label == "likely_ai":
        if has_visual_ai:
            summary = (
                "The image has strong AI-like visual and file signals. Treat this as a risk flag, "
                "not a final proof."
            )
        else:
            summary = "The image has strong AI-related signals. Treat this as a risk flag, not a final proof."
        confidence = max(0.55, min(0.82, analysis.ai_generated_score))
    elif has_camera_metadata:
        summary = (
            "Original camera metadata was found in the file. That supports a camera-photo origin, "
            "but it does not prove the image was never edited."
        )
        confidence = 0.50
    elif has_camera_context:
        summary = (
            "Android MediaStore context says this image came from the phone camera library. "
            "That supports a camera-photo origin, but it is still metadata context rather than proof."
        )
        confidence = 0.56
    elif label == "likely_not_ai":
        summary = "The image has low metadata risk based on available signals, but this is not proof that it is authentic."
        confidence = 0.55
    else:
        if has_weak_visual_ai or analysis.ai_generated_score >= 0.65:
            summary = (
                "The image has some AI-like visual or file signals, but not enough evidence "
                "for a strong AI verdict."
            )
        elif analysis.ai_generated_score >= 0.35:
            summary = (
                "The file has weak metadata or format clues, but the lightweight cloud check "
                "cannot confirm AI generation from metadata alone."
            )
        elif metadata_missing:
            summary = (
                "No original camera metadata or AI-generator metadata was found. The file may have been "
                "exported, edited, downloaded, or stripped of metadata."
            )
        else:
            summary = (
                "No AI-generator metadata was found in the file. This does not prove that the image is real."
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
