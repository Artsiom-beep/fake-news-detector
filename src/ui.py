from __future__ import annotations

import json
from html import escape
from typing import Any

from fastapi import FastAPI, File, Form, UploadFile
from fastapi.responses import HTMLResponse, Response

from src.factcheck.image_analysis import run_ai_image_check
from src.factcheck.service import run_factcheck

app = FastAPI(title="Verity Lens UI", version="1.1")

DEFAULT_PANEL = "newsTool"
VALID_PANELS = {"newsTool", "factsTool", "imagesTool"}


def _normalize_active_panel(value: str | None) -> str:
    return value if value in VALID_PANELS else DEFAULT_PANEL


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def _fmt_score(value: Any) -> str:
    return f"{_as_float(value):.2f}"


def _pct(value: Any) -> str:
    return f"{max(0.0, min(1.0, _as_float(value))) * 100:.1f}%"


def _ai_label_display(ai_label: str) -> tuple[str, str, str]:
    label = (ai_label or "uncertain").lower()
    if label == "likely_ai":
        return "Likely AI", "low", "We found strong AI-generation signals."
    if label == "likely_not_ai":
        return "Likely real", "high", "We found low AI-generation risk."
    return "Not enough certainty", "unknown", "We cannot tell from this image alone."


def _primary_status(result: dict[str, Any]) -> tuple[str, str, float, str]:
    image_analysis = result.get("image_analysis") or {}
    if image_analysis.get("mode") == "ai_image_detection":
        ai_label = (image_analysis.get("ai_label") or "uncertain").lower()
        ai_score = _as_float(image_analysis.get("ai_generated_score", 0.0))
        display, tone, _explanation = _ai_label_display(ai_label)
        return display, tone, ai_score, "AI risk score"

    credibility = result.get("credibility") or {}
    verdict = (result.get("verdict") or "uncertain").lower()
    confidence = _as_float(result.get("confidence", 0.0))

    if credibility:
        label = (credibility.get("label") or "unknown").lower()
        score = _as_float(credibility.get("score", 0.0))
        return f"Credibility: {label}", label if label in {"high", "medium", "low"} else "unknown", score, "Credibility score"
    if verdict == "true":
        return "Likely reliable", "high", confidence, "Confidence"
    if verdict == "fake":
        return "Likely false", "low", confidence, "Confidence"
    return "Not enough certainty", "unknown", confidence, "Confidence"


def _friendly_summary(result: dict[str, Any]) -> str:
    summary = result.get("summary") or ""
    if summary:
        return summary
    status, _, _, _ = _primary_status(result)
    if status == "Not enough certainty":
        return "The app did not find an exact enough source-backed answer."
    return "The app found enough source-backed evidence to make this call."


def _badge(text: str, tone: str) -> str:
    css = {"high": "good", "medium": "warn", "low": "bad", "unknown": "neutral"}.get(tone, "neutral")
    return f"<span class='badge {css}'>{escape(text)}</span>"


def _render_evidence(items: list[dict[str, Any]]) -> str:
    if not items:
        return """
        <div class="soft-empty">
          <strong>No evidence selected.</strong>
          <span>The app either abstained or did not need external evidence for this simple check.</span>
        </div>
        """

    cards = []
    for index, item in enumerate(items[:8], 1):
        title = item.get("title") or item.get("url") or "Untitled source"
        url = item.get("url") or "#"
        passage = item.get("passage") or item.get("snippet") or ""
        stance = (item.get("stance") or "neutral").lower()
        cards.append(
            f"""
            <details class="evidence" {"open" if index == 1 else ""}>
              <summary>
                <span class="source-number">{index}</span>
                <span class="source-title">{escape(title)}</span>
                <span class="source-pill">{escape(stance)}</span>
              </summary>
              <p>{escape(passage)}</p>
              <div class="source-meta">
                <span>score {_fmt_score(item.get("score", 0.0))}</span>
                <span>trust {_fmt_score(item.get("source_trust", 0.0))}</span>
                <span>{escape(item.get("source_type", "unknown"))}</span>
                <span>{escape(item.get("domain", ""))}</span>
              </div>
              <a class="source-link" href="{escape(url)}" target="_blank" rel="noreferrer">Open source</a>
            </details>
            """
        )
    return "\n".join(cards)


def _render_credibility(credibility: dict[str, Any]) -> str:
    if not credibility:
        return ""
    risks = credibility.get("risk_flags") or []
    matched = credibility.get("matched_sources") or []
    risk_text = ", ".join(str(item) for item in risks) if risks else "none"
    return f"""
    <div class="signal-grid">
      <div><span>Source</span><b>{_fmt_score(credibility.get("source_score", 0.0))}</b></div>
      <div><span>Article quality</span><b>{_fmt_score(credibility.get("article_quality_score", 0.0))}</b></div>
      <div><span>Corroboration</span><b>{_fmt_score(credibility.get("corroboration_score", 0.0))}</b></div>
      <div><span>Risk</span><b>{_fmt_score(credibility.get("risk_score", 0.0))}</b></div>
    </div>
    <p class="small-note">Matched sources: {len(matched)}. Risk flags: {escape(risk_text)}.</p>
    """


def _render_image_analysis(image_analysis: dict[str, Any]) -> str:
    if not image_analysis:
        return ""
    mode = image_analysis.get("mode", "image")
    warnings = image_analysis.get("warnings") or []
    reasons = image_analysis.get("reasons") or []
    warning_text = ", ".join(str(item) for item in warnings) if warnings else "none"
    reason_text = ", ".join(str(item) for item in reasons[:4]) if reasons else "none"

    if mode == "screenshot_ocr":
        ocr_text = image_analysis.get("ocr_text") or ""
        urls = image_analysis.get("detected_urls") or []
        return f"""
        <section class="image-card">
          <div class="section-heading">
            <h3>Screenshot text</h3>
            <span>OCR confidence {_fmt_score(image_analysis.get("ocr_confidence", 0.0))}</span>
          </div>
          <pre class="ocr-text">{escape(ocr_text or "No readable text found.")}</pre>
          <p class="small-note">Detected URLs: {escape(", ".join(urls) if urls else "none")}. Warnings: {escape(warning_text)}.</p>
        </section>
        """

    display_label, tone, explanation = _ai_label_display(str(image_analysis.get("ai_label", "uncertain")))
    return f"""
    <section class="image-card">
      <div class="section-heading">
        <h3>Image risk check</h3>
        {_badge(display_label, tone)}
      </div>
      <p>{escape(explanation)} This is a risk assessment, not proof.</p>
      <div class="signal-grid">
        <div><span>AI risk</span><b>{_fmt_score(image_analysis.get("ai_generated_score", 0.0))}</b></div>
        <div><span>Width</span><b>{escape(str((image_analysis.get("metadata") or {}).get("width", "")))}</b></div>
        <div><span>Height</span><b>{escape(str((image_analysis.get("metadata") or {}).get("height", "")))}</b></div>
        <div><span>Format</span><b>{escape(str((image_analysis.get("metadata") or {}).get("format", "")))}</b></div>
      </div>
      <p class="small-note">Reasons: {escape(reason_text)}. Warnings: {escape(warning_text)}.</p>
    </section>
    """


def _render_advanced(result: dict[str, Any]) -> str:
    trace = result.get("trace") or {}
    reasons = trace.get("decision_reasons") or []
    fallbacks = trace.get("fallbacks_used") or []
    timings = trace.get("stage_timings_ms") or {}
    reason_items = "".join(f"<li>{escape(str(item))}</li>" for item in reasons[:60]) or "<li>None</li>"
    fallback_items = "".join(f"<li>{escape(str(item))}</li>" for item in fallbacks[:30]) or "<li>None</li>"
    timing_items = "".join(
        f"<li><span>{escape(str(key))}</span><b>{_as_float(value):.1f} ms</b></li>"
        for key, value in timings.items()
    ) or "<li>None</li>"
    raw_json = escape(json.dumps(result, ensure_ascii=False, indent=2))
    return f"""
    <details class="advanced">
      <summary>Advanced details</summary>
      <div class="advanced-grid">
        <section>
          <h4>Why this answer?</h4>
          <ul>{reason_items}</ul>
        </section>
        <section>
          <h4>Fallbacks</h4>
          <ul>{fallback_items}</ul>
        </section>
        <section>
          <h4>Timing</h4>
          <ul class="timings">{timing_items}</ul>
        </section>
      </div>
      <details class="raw-json">
        <summary>Raw JSON</summary>
        <pre>{raw_json}</pre>
      </details>
    </details>
    """


def _render_result(result: dict[str, Any]) -> str:
    status, tone, score, score_label = _primary_status(result)
    claim = result.get("claim") or "No checkable claim found"
    credibility = result.get("credibility") or {}
    image_analysis = result.get("image_analysis") or {}
    evidence = result.get("evidence") or []
    verdict = result.get("verdict") or "uncertain"
    return f"""
    <section class="answer-card {tone}">
      <div class="answer-top">
        {_badge(status, tone)}
        <span class="verdict-note">Fact-check verdict: {escape(verdict)}</span>
      </div>
      <h2>{escape(claim)}</h2>
      <p>{escape(_friendly_summary(result))}</p>
      {_render_credibility(credibility)}
      {_render_image_analysis(image_analysis)}
      <div class="score-line">
        <span>{escape(score_label)}</span>
        <strong>{score:.2f}</strong>
      </div>
      <div class="meter"><span style="width:{_pct(score)}"></span></div>
    </section>

    <section class="sources-card">
      <div class="section-heading">
        <h3>Evidence</h3>
        <span>{len(evidence)} selected source{"s" if len(evidence) != 1 else ""}</span>
      </div>
      {_render_evidence(evidence)}
    </section>

    {_render_advanced(result)}
    """


def render_page(
    result_html: str = "",
    error_html: str = "",
    url_value: str = "",
    text_value: str = "",
    active_panel: str = DEFAULT_PANEL,
) -> str:
    active_panel = _normalize_active_panel(active_panel)

    def menu_selected(panel_id: str) -> str:
        return "true" if panel_id == active_panel else "false"

    def panel_class(base_class: str, panel_id: str) -> str:
        active_class = " active" if panel_id == active_panel else ""
        return f"tool-card {base_class}{active_class}"

    def aria_hidden(panel_id: str) -> str:
        return "false" if panel_id == active_panel else "true"

    news_url_value = url_value if active_panel == "newsTool" else ""
    news_text_value = text_value if active_panel == "newsTool" else ""
    fact_text_value = text_value if active_panel == "factsTool" else ""
    image_text_value = text_value if active_panel == "imagesTool" else ""

    return f"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Verity Lens</title>
  <style>
    :root {{
      --bg:#f6eee5;
      --card:#fffaf4;
      --ink:#18202f;
      --muted:#6a6271;
      --line:#e3d4c2;
      --blue:#315f72;
      --blue-2:#e2f0f3;
      --green:#146c48;
      --green-bg:#dff4e7;
      --red:#963333;
      --red-bg:#f6dddd;
      --amber:#9a6400;
      --amber-bg:#fff0c4;
      --neutral:#475467;
      --neutral-bg:#f0edf0;
      --shadow:0 18px 42px rgba(72,46,28,.12);
    }}
    * {{ box-sizing:border-box; }}
    html {{ scroll-behavior:smooth; }}
    body {{
      margin:0;
      min-height:100vh;
      color:var(--ink);
      font-family:"Segoe UI", "Aptos", sans-serif;
      background:var(--bg);
    }}
    body::before {{
      content:"";
      position:fixed;
      inset:0;
      pointer-events:none;
      opacity:.42;
      background-image:linear-gradient(rgba(93,60,39,.045) 1px, transparent 1px), linear-gradient(90deg, rgba(93,60,39,.045) 1px, transparent 1px);
      background-size:32px 32px;
      mask-image:linear-gradient(to bottom, black, transparent 78%);
    }}
    a {{ color:var(--blue); }}
    .app {{
      width:min(1100px, calc(100% - 28px));
      margin:0 auto;
      padding:26px 0 46px;
      position:relative;
    }}
    .shell {{
      display:grid;
      grid-template-columns:1fr;
      gap:16px;
    }}
    .hero, .tool-card, .answer-card, .sources-card, .advanced {{
      border:1px solid var(--line);
      background:var(--card);
      border-radius:8px;
      box-shadow:var(--shadow);
    }}
    .hero {{
      padding:22px 24px;
      display:grid;
      gap:12px;
      overflow:hidden;
      position:relative;
    }}
    .kicker {{
      color:#846044;
      font-size:12px;
      font-weight:900;
      letter-spacing:0;
      text-transform:uppercase;
    }}
    h1 {{
      margin:0;
      max-width:760px;
      font-family:Georgia, Cambria, serif;
      font-size:48px;
      line-height:1;
      letter-spacing:0;
    }}
    .hero p {{
      margin:0;
      max-width:690px;
      color:#665f6d;
      font-size:17px;
      line-height:1.55;
    }}
    .composer {{
      display:grid;
      grid-template-columns:250px minmax(0, 1fr);
      align-items:start;
      gap:16px;
    }}
    .section-menu {{
      position:sticky;
      top:14px;
      z-index:5;
      display:grid;
      gap:8px;
      padding:8px;
      border:1px solid var(--line);
      border-radius:8px;
      background:rgba(255,250,244,.94);
      box-shadow:var(--shadow);
      backdrop-filter:blur(14px);
    }}
    .menu-item {{
      --mode:#9a6040;
      --mode-bg:#fff1e8;
      min-height:58px;
      border:1px solid var(--line);
      border-radius:8px;
      padding:10px 12px;
      color:#263246;
      background:#fffaf4;
      font-size:14px;
      font-weight:900;
      text-align:left;
      cursor:pointer;
      transition:background .18s ease, border-color .18s ease, color .18s ease, transform .18s ease;
    }}
    .menu-item span {{
      display:block;
      font-size:15px;
    }}
    .menu-item b {{
      display:block;
      margin-top:4px;
      color:var(--muted);
      font-size:11px;
      font-weight:900;
      text-transform:uppercase;
    }}
    .menu-item:hover {{
      transform:translateX(2px);
      border-color:var(--mode);
      background:var(--mode-bg);
    }}
    .menu-item[aria-selected="true"] {{
      color:white;
      border-color:var(--mode);
      background:var(--mode);
      box-shadow:0 12px 24px rgba(83,48,32,.20);
    }}
    .menu-item[aria-selected="true"] b {{
      color:rgba(255,255,255,.82);
    }}
    .menu-item.news-mode {{ --mode:#a95f3d; --mode-bg:#fff0e5; }}
    .menu-item.facts-mode {{ --mode:#8b6a16; --mode-bg:#fff4ce; }}
    .menu-item.images-mode {{ --mode:#8d4d6f; --mode-bg:#fae8f2; }}
    .tool-stage {{
      min-width:0;
      scroll-margin-top:16px;
    }}
    .tool-card {{
      --mode:#a95f3d;
      --mode-bg:#fff0e5;
      --mode-border:#edc6b5;
      display:none;
      padding:22px;
      min-width:0;
      min-height:540px;
      opacity:0;
      transform:translateY(8px);
      border-top:4px solid var(--mode);
      background:
        linear-gradient(180deg, var(--mode-bg), transparent 108px),
        var(--card);
    }}
    .tool-card.news {{ --mode:#a95f3d; --mode-bg:#fff0e5; --mode-border:#edc6b5; }}
    .tool-card.facts {{ --mode:#8b6a16; --mode-bg:#fff4ce; --mode-border:#ead17c; }}
    .tool-card.image {{ --mode:#8d4d6f; --mode-bg:#fae8f2; --mode-border:#e7bdd2; }}
    .tool-card.active {{
      display:block;
      animation:panelIn .22s ease-out forwards;
    }}
    @keyframes panelIn {{
      from {{ opacity:0; transform:translateY(8px); }}
      to {{ opacity:1; transform:translateY(0); }}
    }}
    .tool-head {{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      gap:12px;
      margin-bottom:14px;
    }}
    .tool-title {{
      min-width:0;
    }}
    .tool-head h2 {{
      margin:0;
      font-family:Georgia, Cambria, serif;
      font-size:28px;
      line-height:1.08;
      letter-spacing:0;
    }}
    .tool-kind {{
      border-radius:8px;
      padding:6px 9px;
      color:var(--mode);
      background:var(--mode-bg);
      font-size:11px;
      font-weight:1000;
      text-transform:uppercase;
      white-space:nowrap;
    }}
    .tool-actions {{
      display:flex;
      align-items:center;
      gap:8px;
      flex-wrap:wrap;
      justify-content:flex-end;
    }}
    .info-btn {{
      border:1px solid var(--mode-border);
      border-radius:8px;
      padding:7px 10px;
      color:var(--mode);
      background:rgba(255,250,244,.78);
      font-size:12px;
      font-weight:900;
      cursor:pointer;
    }}
    .info-btn[aria-expanded="true"] {{
      color:white;
      border-color:var(--mode);
      background:var(--mode);
    }}
    .info-panel {{
      margin:-2px 0 14px;
      padding:14px;
      border:1px solid var(--mode-border);
      border-radius:8px;
      background:rgba(255,250,244,.82);
    }}
    .info-panel[hidden] {{
      display:none;
    }}
    .info-panel h3 {{
      margin:0 0 8px;
      color:var(--mode);
      font-family:"Segoe UI", "Aptos", sans-serif;
      font-size:16px;
      letter-spacing:0;
    }}
    .info-panel p {{
      margin:0;
      color:#4f4a55;
      font-size:14px;
      line-height:1.5;
    }}
    .info-panel p + p {{
      margin-top:8px;
    }}
    .tool-form {{
      display:grid;
      gap:12px;
    }}
    label {{
      display:block;
      margin:0 0 8px;
      font-size:14px;
      font-weight:900;
      color:#2f3a4c;
    }}
    .url-input, textarea {{
      width:100%;
      border:1px solid #dccbbb;
      background:rgba(255,252,247,.96);
      color:var(--ink);
      border-radius:8px;
      padding:14px 16px;
      font:inherit;
      outline:none;
    }}
    .file-input {{
      display:none;
    }}
    .paste-zone, .media-drop {{
      display:grid;
      grid-template-columns:1fr auto;
      gap:12px;
      align-items:center;
      margin-top:10px;
      padding:14px;
      border:1px dashed var(--mode-border);
      border-radius:8px;
      background:rgba(255,250,244,.76);
      color:#465367;
      outline:none;
      cursor:pointer;
    }}
    .paste-zone:focus, .paste-zone.drag-over, .media-drop:focus, .media-drop.drag-over {{
      border-color:var(--mode);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--mode) 18%, transparent);
      background:var(--mode-bg);
    }}
    .paste-zone strong, .media-drop strong {{
      display:block;
      color:#263246;
      font-size:15px;
      margin-bottom:3px;
    }}
    .paste-zone span, .media-drop span {{
      color:var(--muted);
      font-size:13px;
      line-height:1.4;
    }}
    .image-preview {{
      display:none;
      width:92px;
      height:70px;
      object-fit:cover;
      border-radius:8px;
      border:1px solid #d5dde6;
      background:#fff;
    }}
    .paste-zone.has-image .image-preview, .media-drop.has-image .image-preview {{
      display:block;
    }}
    textarea {{
      min-height:150px;
      resize:vertical;
      font-size:16px;
      line-height:1.55;
    }}
    .tool-card textarea {{
      min-height:180px;
    }}
    .tool-card.news textarea {{
      min-height:150px;
    }}
    .tool-card.image textarea {{
      min-height:110px;
    }}
    .url-input:focus, textarea:focus {{
      border-color:var(--mode);
      box-shadow:0 0 0 4px color-mix(in srgb, var(--mode) 18%, transparent);
    }}
    .composer-actions {{
      display:flex;
      align-items:center;
      justify-content:space-between;
      gap:14px;
      flex-wrap:wrap;
    }}
    .primary-btn {{
      border:0;
      border-radius:8px;
      padding:14px 22px;
      color:white;
      background:var(--mode);
      font-weight:900;
      letter-spacing:0;
      cursor:pointer;
      box-shadow:0 14px 28px color-mix(in srgb, var(--mode) 28%, transparent);
    }}
    .primary-btn:hover {{
      filter:brightness(.94);
    }}
    .button-row {{
      display:flex;
      flex-wrap:wrap;
      gap:8px;
    }}
    .secondary-btn {{
      border:1px solid var(--mode-border);
      border-radius:8px;
      padding:13px 16px;
      color:#263246;
      background:rgba(255,255,255,.58);
      font-weight:900;
      cursor:pointer;
    }}
    .primary-btn:disabled {{ opacity:.68; cursor:wait; }}
    .file-chip {{
      display:inline-flex;
      align-items:center;
      justify-content:center;
      border:1px solid #cfd8e3;
      border-radius:8px;
      padding:10px 12px;
      color:#263246;
      background:rgba(255,250,244,.86);
      font-size:13px;
      font-weight:900;
      cursor:pointer;
    }}
    .helper {{
      color:var(--muted);
      font-size:13px;
      margin:9px 0 0;
      line-height:1.45;
    }}
    .error {{
      padding:14px 16px;
      border:1px solid #d89a9a;
      background:#f8dfdf;
      color:#7a2323;
      border-radius:8px;
      font-weight:800;
    }}
    .answer-card {{
      padding:24px;
    }}
    .answer-card.high {{ background:linear-gradient(135deg, rgba(223,244,231,.96), rgba(255,250,241,.95)); }}
    .answer-card.medium {{ background:linear-gradient(135deg, rgba(255,240,196,.96), rgba(255,250,241,.95)); }}
    .answer-card.low {{ background:linear-gradient(135deg, rgba(246,221,221,.96), rgba(255,250,241,.95)); }}
    .answer-card.unknown {{ background:linear-gradient(135deg, rgba(238,241,244,.96), rgba(255,250,241,.95)); }}
    .answer-top {{
      display:flex;
      gap:10px;
      align-items:center;
      flex-wrap:wrap;
    }}
    .badge {{
      display:inline-flex;
      width:max-content;
      border-radius:8px;
      padding:8px 12px;
      font-size:12px;
      font-weight:1000;
      letter-spacing:0;
      text-transform:uppercase;
    }}
    .badge.good {{ color:var(--green); background:var(--green-bg); }}
    .badge.warn {{ color:var(--amber); background:var(--amber-bg); }}
    .badge.bad {{ color:var(--red); background:var(--red-bg); }}
    .badge.neutral {{ color:var(--neutral); background:var(--neutral-bg); }}
    .verdict-note {{
      color:var(--muted);
      font-size:13px;
      font-weight:800;
    }}
    h2 {{
      margin:16px 0 8px;
      font-family:Georgia, Cambria, serif;
      font-size:36px;
      line-height:1.08;
      letter-spacing:0;
    }}
    .answer-card p {{
      color:#465367;
      font-size:16px;
      line-height:1.55;
      margin:0;
    }}
    .score-line {{
      display:flex;
      justify-content:space-between;
      align-items:end;
      margin-top:18px;
      color:#5b6678;
      font-weight:900;
    }}
    .score-line strong {{
      color:var(--ink);
      font-size:38px;
      letter-spacing:0;
    }}
    .meter {{
      height:13px;
      overflow:hidden;
      border-radius:8px;
      background:#e7d9c5;
      border:1px solid #d7c4aa;
    }}
    .meter span {{
      display:block;
      height:100%;
      border-radius:8px;
      background:linear-gradient(90deg, #c78922, #2f7590);
    }}
    .signal-grid {{
      display:grid;
      grid-template-columns:repeat(4, minmax(0, 1fr));
      gap:10px;
      margin:16px 0 4px;
    }}
    .signal-grid div {{
      padding:12px;
      border-radius:8px;
      border:1px solid #dfcfb8;
      background:rgba(255,255,255,.48);
    }}
    .signal-grid span {{
      display:block;
      color:var(--muted);
      font-size:12px;
      margin-bottom:4px;
    }}
    .signal-grid b {{ font-size:19px; }}
    .small-note {{
      margin-top:8px !important;
      color:var(--muted) !important;
      font-size:13px !important;
    }}
    .sources-card, .advanced, .image-card {{
      padding:20px;
    }}
    .image-card {{
      margin-top:18px;
      border:1px solid #dfcfb8;
      border-radius:8px;
      background:rgba(255,255,255,.44);
      box-shadow:none;
    }}
    .section-heading {{
      display:flex;
      justify-content:space-between;
      gap:12px;
      align-items:end;
      margin-bottom:12px;
    }}
    h3, h4 {{
      margin:0;
      letter-spacing:0;
    }}
    h3 {{
      font-family:Georgia, Cambria, serif;
      font-size:28px;
    }}
    .section-heading span {{
      color:var(--muted);
      font-size:13px;
      font-weight:800;
    }}
    .soft-empty {{
      display:grid;
      gap:4px;
      padding:16px;
      color:#5b6678;
      border:1px dashed #ccb99e;
      border-radius:8px;
      background:rgba(255,255,255,.46);
    }}
    .evidence {{
      border:1px solid #ddcdb5;
      border-radius:8px;
      background:rgba(255,253,248,.72);
      margin-top:10px;
      overflow:hidden;
    }}
    .evidence summary {{
      display:grid;
      grid-template-columns:auto 1fr auto;
      gap:10px;
      align-items:center;
      padding:13px;
      cursor:pointer;
      font-weight:900;
    }}
    .source-number {{
      width:30px;
      height:30px;
      display:grid;
      place-items:center;
      border-radius:8px;
      color:white;
      background:#1f2937;
      font-size:13px;
    }}
    .source-title {{ overflow-wrap:anywhere; }}
    .source-pill {{
      padding:5px 8px;
      border-radius:8px;
      background:#edf0f3;
      color:#475467;
      font-size:11px;
      text-transform:uppercase;
    }}
    .evidence p {{
      margin:0;
      padding:0 14px 10px 54px;
      color:#475467;
      line-height:1.55;
    }}
    .source-meta {{
      display:flex;
      flex-wrap:wrap;
      gap:7px;
      padding:0 14px 12px 54px;
    }}
    .source-meta span {{
      border-radius:8px;
      background:#f0e3d1;
      color:#566174;
      font-size:12px;
      padding:5px 8px;
    }}
    .source-link {{
      display:inline-block;
      margin:0 14px 14px 54px;
      font-weight:900;
      text-decoration:none;
    }}
    .advanced {{
      margin-bottom:22px;
    }}
    .advanced > summary {{
      cursor:pointer;
      font-size:16px;
      font-weight:1000;
    }}
    .advanced-grid {{
      display:grid;
      grid-template-columns:1fr 1fr 1fr;
      gap:12px;
      margin-top:16px;
    }}
    .advanced section {{
      border:1px solid #dfcfb8;
      border-radius:8px;
      background:rgba(255,255,255,.46);
      padding:14px;
      min-width:0;
    }}
    .advanced ul {{
      margin:10px 0 0;
      padding-left:20px;
      color:#526073;
      max-height:240px;
      overflow:auto;
    }}
    .advanced li {{
      margin:6px 0;
      overflow-wrap:anywhere;
    }}
    .timings li {{
      display:flex;
      justify-content:space-between;
      gap:12px;
    }}
    .raw-json {{
      margin-top:12px;
      border:1px solid #dfcfb8;
      border-radius:8px;
      overflow:hidden;
    }}
    .raw-json summary {{
      cursor:pointer;
      padding:12px 14px;
      font-weight:900;
      background:rgba(255,255,255,.42);
    }}
    pre {{
      margin:0;
      padding:14px;
      max-height:480px;
      overflow:auto;
      color:#f8fafc;
      background:#172033;
      font-size:12px;
      line-height:1.45;
    }}
    .ocr-text {{
      background:rgba(255,253,248,.78);
      color:#263246;
      border:1px solid #dfcfb8;
      border-radius:8px;
      max-height:220px;
      white-space:pre-wrap;
    }}
    @media (max-width: 760px) {{
      .app {{ width:min(100% - 16px, 1040px); padding:8px 0 28px; }}
      .hero, .tool-card, .answer-card, .sources-card, .advanced, .image-card {{ border-radius:8px; }}
      .hero {{ padding:18px; }}
      h1 {{ font-size:36px; }}
      h2 {{ font-size:30px; }}
      .composer {{ grid-template-columns:1fr; gap:10px; }}
      .section-menu {{
        top:0;
        grid-template-columns:repeat(2, minmax(0, 1fr));
        gap:6px;
        padding:6px;
      }}
      .menu-item {{
        min-height:52px;
        text-align:center;
      }}
      .menu-item:hover {{
        transform:none;
      }}
      .tool-stage {{ scroll-margin-top:82px; }}
      .tool-card {{
        min-height:auto;
        padding:18px;
      }}
      .tool-head {{
        align-items:flex-start;
      }}
      .tool-actions {{
        justify-content:flex-end;
      }}
      .media-drop {{
        grid-template-columns:1fr;
      }}
      .image-preview {{
        width:100%;
        height:160px;
      }}
      .composer-actions {{ align-items:stretch; }}
      .primary-btn, .secondary-btn, .button-row {{ width:100%; }}
      .signal-grid, .advanced-grid {{ grid-template-columns:1fr; }}
      .evidence summary {{ grid-template-columns:auto 1fr; }}
      .source-pill {{ grid-column:2; width:max-content; }}
      .evidence p, .source-meta, .source-link {{ margin-left:0; padding-left:14px; }}
    }}
  </style>
</head>
<body>
  <main class="app">
    <div class="shell">
      <section class="hero">
            <div class="kicker">Verity Lens</div>
        <h1>Verification workspace</h1>
        <p>News, claims, and images have separate checks.</p>
      </section>

      <section class="composer">
        <nav class="section-menu" aria-label="Verification menu">
          <button class="menu-item news-mode" type="button" data-target="newsTool" aria-selected="{menu_selected("newsTool")}">
            <span>News</span>
            <b>URL</b>
          </button>
          <button class="menu-item facts-mode" type="button" data-target="factsTool" aria-selected="{menu_selected("factsTool")}">
            <span>Facts</span>
            <b>Claim</b>
          </button>
          <button class="menu-item images-mode" type="button" data-target="imagesTool" aria-selected="{menu_selected("imagesTool")}">
            <span>Images</span>
            <b>AI risk</b>
          </button>
        </nav>

        <div class="tool-stage" id="toolStage">
          <article class="{panel_class("news", "newsTool")}" id="newsTool" data-panel="newsTool" aria-hidden="{aria_hidden("newsTool")}">
            <div class="tool-head">
              <div class="tool-title">
                <h2>News</h2>
              </div>
              <div class="tool-actions">
                <button class="info-btn" type="button" data-info-toggle aria-expanded="false" aria-controls="newsGuide">Guide</button>
                <span class="tool-kind">URL</span>
              </div>
            </div>
            <div class="info-panel" id="newsGuide" hidden>
              <h3>What this mode does</h3>
              <p>Checks a news URL, reads the article shape, scores the source, looks for risk flags, and returns a credibility result instead of forcing true or fake.</p>
              <p><strong>Example:</strong> paste a Reuters or AP article URL, then use Check news to see source score, article quality, corroboration, and selected evidence.</p>
            </div>
            <form class="tool-form" method="post" action="/check#newsTool" enctype="multipart/form-data">
              <input type="hidden" name="active_panel" value="newsTool" />
              <label for="newsUrlInput">News URL</label>
              <input class="url-input" id="newsUrlInput" type="text" name="url" value="{escape(news_url_value)}" placeholder="https://news-site.com/article" />
              <label for="newsTextInput">Article note</label>
              <textarea id="newsTextInput" name="text" placeholder="Optional claim inside the article">{escape(news_text_value)}</textarea>
              <div class="composer-actions">
                <button class="primary-btn" type="submit" data-loading="Checking news...">Check news</button>
              </div>
            </form>
          </article>

          <article class="{panel_class("facts", "factsTool")}" id="factsTool" data-panel="factsTool" aria-hidden="{aria_hidden("factsTool")}">
            <div class="tool-head">
              <div class="tool-title">
                <h2>Facts</h2>
              </div>
              <div class="tool-actions">
                <button class="info-btn" type="button" data-info-toggle aria-expanded="false" aria-controls="factsGuide">Guide</button>
                <span class="tool-kind">Claim</span>
              </div>
            </div>
            <div class="info-panel" id="factsGuide" hidden>
              <h3>What this mode does</h3>
              <p>Checks a single claim against stable built-in facts, trusted evidence, and fact-check sources. If the evidence is weak, it returns not enough certainty.</p>
              <p><strong>Example:</strong> type “Elephant is a mammal” to get a likely reliable result, or “Coffee cures cancer” to see the system abstain.</p>
            </div>
            <form class="tool-form" method="post" action="/check#factsTool" enctype="multipart/form-data">
              <input type="hidden" name="active_panel" value="factsTool" />
              <label for="factTextInput">Claim</label>
              <textarea id="factTextInput" name="text" placeholder="Example: Elephant is a mammal">{escape(fact_text_value)}</textarea>
              <div class="composer-actions">
                <button class="primary-btn" type="submit" data-loading="Checking fact...">Check fact</button>
              </div>
            </form>
          </article>

          <article class="{panel_class("image", "imagesTool")}" id="imagesTool" data-panel="imagesTool" aria-hidden="{aria_hidden("imagesTool")}">
            <div class="tool-head">
              <div class="tool-title">
                <h2>Photos / images</h2>
              </div>
              <div class="tool-actions">
                <button class="info-btn" type="button" data-info-toggle aria-expanded="false" aria-controls="imagesGuide">Guide</button>
                <span class="tool-kind">AI risk</span>
              </div>
            </div>
            <div class="info-panel" id="imagesGuide" hidden>
              <h3>What this mode does</h3>
              <p>Checks image metadata and model signals for AI-generation risk. It can say likely AI, likely real, or not enough certainty.</p>
              <p><strong>Example:</strong> upload an AI-generated portrait or a real photo, then use Detect AI image to see the risk score and reasons.</p>
            </div>
            <form class="tool-form" method="post" action="/check#imagesTool" enctype="multipart/form-data" data-media-picker>
              <input type="hidden" name="active_panel" value="imagesTool" />
              <input type="hidden" name="image_action" value="ai_image" />
              <label for="imageQuestionInput">Context</label>
              <textarea id="imageQuestionInput" name="text" placeholder="Optional image context">{escape(image_text_value)}</textarea>
              <input class="file-input" id="imageInput" type="file" name="image_file" accept="image/png,image/jpeg,image/webp,image/bmp,image/tiff" />
              <div class="media-drop" tabindex="0" aria-label="Image upload area">
                <div>
                  <strong data-media-title>Photo or generated image</strong>
                  <span data-media-status>Paste, drop, or choose an image file.</span>
                </div>
                <img class="image-preview" data-media-preview alt="Selected image preview" />
              </div>
              <label class="file-chip" for="imageInput">Choose image</label>
              <div class="composer-actions">
                <button class="primary-btn" type="submit" data-loading="Detecting image...">Detect AI image</button>
              </div>
            </form>
          </article>
        </div>
      </section>

      {error_html}
      {result_html}
    </div>
  </main>

  <script>
    const menuItems = Array.from(document.querySelectorAll('[data-target]'));
    const panels = Array.from(document.querySelectorAll('[data-panel]'));
    const toolStage = document.getElementById('toolStage');
    const infoButtons = Array.from(document.querySelectorAll('[data-info-toggle]'));
    const mediaPickers = Array.from(document.querySelectorAll('[data-media-picker]'));
    let activeMediaPicker = mediaPickers[0] || null;

    function activatePanel(panelId, shouldScroll) {{
      const targetPanel = panels.find((panel) => panel.id === panelId) || panels[0];
      if (!targetPanel) {{
        return;
      }}
      panels.forEach((panel) => {{
        const isActive = panel === targetPanel;
        panel.classList.toggle('active', isActive);
        panel.setAttribute('aria-hidden', isActive ? 'false' : 'true');
      }});
      menuItems.forEach((item) => {{
        const isActive = item.dataset.target === targetPanel.id;
        item.setAttribute('aria-selected', isActive ? 'true' : 'false');
      }});
      const mediaPicker = targetPanel.querySelector('[data-media-picker]');
      if (mediaPicker) {{
        activeMediaPicker = mediaPicker;
      }}
      if (shouldScroll && toolStage) {{
        toolStage.scrollIntoView({{ behavior: 'smooth', block: 'start' }});
      }}
    }}

    menuItems.forEach((item) => {{
      item.addEventListener('click', () => {{
        activatePanel(item.dataset.target, true);
        if (history.replaceState) {{
          history.replaceState(null, '', '#' + item.dataset.target);
        }}
      }});
    }});

    if (window.location.hash) {{
      activatePanel(window.location.hash.slice(1), false);
    }}

    window.addEventListener('hashchange', () => {{
      if (window.location.hash) {{
        activatePanel(window.location.hash.slice(1), false);
      }}
    }});

    infoButtons.forEach((button) => {{
      button.addEventListener('click', () => {{
        const panel = document.getElementById(button.getAttribute('aria-controls'));
        if (!panel) {{
          return;
        }}
        const isOpen = button.getAttribute('aria-expanded') === 'true';
        button.setAttribute('aria-expanded', isOpen ? 'false' : 'true');
        panel.hidden = isOpen;
      }});
    }});

    function extensionFromMime(mime) {{
      const mapping = {{
        'image/jpeg': 'jpg',
        'image/png': 'png',
        'image/webp': 'webp',
        'image/bmp': 'bmp',
        'image/tiff': 'tiff'
      }};
      return mapping[mime] || 'png';
    }}

    function setSelectedImage(picker, file) {{
      if (!file || !file.type || !file.type.startsWith('image/')) {{
        return false;
      }}
      const imageInput = picker.querySelector('input[type="file"]');
      const dropTarget = picker.querySelector('.media-drop');
      const title = picker.querySelector('[data-media-title]');
      const status = picker.querySelector('[data-media-status]');
      const preview = picker.querySelector('[data-media-preview]');
      const dataTransfer = new DataTransfer();
      dataTransfer.items.add(file);
      imageInput.files = dataTransfer.files;
      if (picker.dataset.previewUrl) {{
        URL.revokeObjectURL(picker.dataset.previewUrl);
      }}
      picker.dataset.previewUrl = URL.createObjectURL(file);
      preview.src = picker.dataset.previewUrl;
      dropTarget.classList.add('has-image');
      title.innerText = 'Image ready';
      status.innerText = file.name + ' · ' + Math.round(file.size / 1024) + ' KB';
      return true;
    }}

    function fileFromClipboardItem(item) {{
      const blob = item.getAsFile();
      if (!blob) {{
        return null;
      }}
      const ext = extensionFromMime(blob.type);
      return new File([blob], 'pasted-image.' + ext, {{ type: blob.type || 'image/png' }});
    }}

    window.addEventListener('paste', (event) => {{
      const items = Array.from((event.clipboardData && event.clipboardData.items) || []);
      const imageItem = items.find((item) => item.type && item.type.startsWith('image/'));
      if (!imageItem) {{
        return;
      }}
      const file = fileFromClipboardItem(imageItem);
      if (activeMediaPicker && file && setSelectedImage(activeMediaPicker, file)) {{
        event.preventDefault();
        activeMediaPicker.querySelector('.media-drop').focus();
      }}
    }});

    mediaPickers.forEach((picker) => {{
      const input = picker.querySelector('input[type="file"]');
      const dropTarget = picker.querySelector('.media-drop');
      const activate = () => {{
        activeMediaPicker = picker;
      }};

      dropTarget.addEventListener('focus', activate);
      dropTarget.addEventListener('mouseenter', activate);
      dropTarget.addEventListener('click', (event) => {{
        if (event.target.tagName.toLowerCase() !== 'label') {{
          input.click();
        }}
      }});
      dropTarget.addEventListener('dragover', (event) => {{
        event.preventDefault();
        activate();
        dropTarget.classList.add('drag-over');
      }});
      dropTarget.addEventListener('dragleave', () => {{
        dropTarget.classList.remove('drag-over');
      }});
      dropTarget.addEventListener('drop', (event) => {{
        event.preventDefault();
        dropTarget.classList.remove('drag-over');
        const files = Array.from((event.dataTransfer && event.dataTransfer.files) || []);
        const imageFile = files.find((file) => file.type && file.type.startsWith('image/'));
        if (imageFile) {{
          setSelectedImage(picker, imageFile);
        }}
      }});
      input.addEventListener('change', () => {{
        const file = input.files && input.files[0];
        if (file) {{
          setSelectedImage(picker, file);
        }}
      }});
    }});

    document.querySelectorAll('form').forEach((form) => {{
      form.addEventListener('submit', (event) => {{
        const button = event.submitter || form.querySelector('button[type="submit"]');
        if (button) {{
          button.disabled = true;
          button.innerText = button.dataset.loading || 'Checking...';
        }}
      }});
    }});
  </script>
</body>
</html>
"""


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    svg = """<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 64 64'>
    <rect width='64' height='64' rx='16' fill='#18202f'/>
    <circle cx='29' cy='29' r='14' fill='none' stroke='#fff8ec' stroke-width='5'/>
    <path d='M40 40l10 10' stroke='#fff8ec' stroke-width='5' stroke-linecap='round'/>
    <path d='M22 28l5 5 10-12' fill='none' stroke='#dff4e7' stroke-width='5' stroke-linecap='round' stroke-linejoin='round'/>
    </svg>"""
    return Response(content=svg, media_type="image/svg+xml")


@app.get("/", response_class=HTMLResponse)
def home() -> str:
    return render_page()


@app.get("/check", response_class=HTMLResponse)
def check_page() -> str:
    return render_page()


@app.post("/check", response_class=HTMLResponse)
async def check(
    url: str = Form(default=""),
    text: str = Form(default=""),
    active_panel: str = Form(default=DEFAULT_PANEL),
    image_action: str = Form(default=""),
    image_file: UploadFile | None = File(default=None),
) -> str:
    active_panel = _normalize_active_panel(active_panel)
    clean_url = (url or "").strip()
    clean_text = (text or "").strip()

    image_bytes = b""
    if image_file is not None and image_file.filename:
        image_bytes = await image_file.read()

    if image_bytes:
        try:
            active_panel = "imagesTool"
            result = run_ai_image_check(
                image_bytes,
                filename=image_file.filename or "",
                question=clean_text,
            ).to_public_dict()
        except Exception as exc:
            error_html = f"<div class='error'>Image check failed: {escape(str(exc))}</div>"
            return render_page(error_html=error_html, url_value=url, text_value=text, active_panel=active_panel)
        return render_page(result_html=_render_result(result), url_value=url, text_value=text, active_panel=active_panel)

    if not clean_url and not clean_text:
        error_html = "<div class='error'>Please paste a URL or a claim first.</div>"
        return render_page(error_html=error_html, url_value=url, text_value=text, active_panel=active_panel)

    result = run_factcheck(text=clean_text, url=clean_url).to_public_dict()
    if not result.get("claim") and result.get("summary", "").startswith("The provided URL"):
        error_html = f"<div class='error'>{escape(result.get('summary', 'Invalid URL'))}</div>"
        return render_page(error_html=error_html, url_value=url, text_value=text, active_panel=active_panel)

    return render_page(result_html=_render_result(result), url_value=url, text_value=text, active_panel=active_panel)
