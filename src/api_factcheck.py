from __future__ import annotations

import json
import os
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

try:
    from .factcheck.common_knowledge import add_user_common_fact, list_user_common_facts
    from .factcheck.image_analysis import run_ai_image_check, run_screenshot_factcheck
    from .factcheck.service import run_factcheck
except ImportError:
    from factcheck.common_knowledge import add_user_common_fact, list_user_common_facts
    from factcheck.image_analysis import run_ai_image_check, run_screenshot_factcheck
    from factcheck.service import run_factcheck

app = FastAPI(title="FactCheck API", version="1.0")


def _cors_origins_from_env() -> list[str]:
    raw = os.getenv("FACTCHECK_CORS_ORIGINS", "*").strip()
    if not raw or raw == "*":
        return ["*"]
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins_from_env(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
)


class FactCheckRequest(BaseModel):
    text: str | None = ""
    url: str | None = ""

    class Config:
        extra = "ignore"


class KnowledgeFactRequest(BaseModel):
    subject: str | None = ""
    property: str | None = None
    property_text: str | None = None
    truth: bool = True
    source_title: str | None = ""
    source_url: str | None = ""

    class Config:
        extra = "ignore"


def _parse_metadata_context(raw: str) -> dict[str, Any]:
    if not raw or not raw.strip():
        return {}
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    if not isinstance(decoded, dict):
        return {}
    return decoded


@app.get("/health")
def health():
    return {"status": "ok", "service": "factcheck"}


@app.get("/ready")
def ready():
    return {"status": "ready", "service": "factcheck"}


@app.post("/factcheck")
def factcheck(request: FactCheckRequest):
    if not (request.text or request.url):
        raise HTTPException(status_code=400, detail={"error": "Provide text or url"})

    result = run_factcheck(text=(request.text or "").strip(), url=(request.url or "").strip())
    payload = result.to_public_dict()
    if not payload.get("claim") and request.url and payload["summary"].startswith("The provided URL"):
        raise HTTPException(status_code=400, detail={"error": payload["summary"], "trace": payload.get("trace", {})})
    return payload


@app.get("/knowledge/facts")
def knowledge_facts():
    return {"facts": list_user_common_facts()}


@app.post("/knowledge/facts")
def add_knowledge_fact(request: KnowledgeFactRequest):
    subject = (request.subject or "").strip()
    property_text = (request.property_text or request.property or "").strip()
    if not subject or not property_text:
        raise HTTPException(status_code=400, detail={"error": "Provide a subject and a property"})
    try:
        fact = add_user_common_fact(
            subject=subject,
            property_text=property_text,
            truth=request.truth,
            source_title=request.source_title or "",
            source_url=request.source_url or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
    return {"status": "added", "fact": fact}


@app.post("/factcheck-image")
async def factcheck_image(
    image_file: UploadFile = File(...),
    analysis_type: str = Form(default="screenshot"),
    question: str = Form(default=""),
    metadata_context: str = Form(default=""),
):
    image_bytes = await image_file.read()
    if not image_bytes:
        raise HTTPException(status_code=400, detail={"error": "Provide an image file"})
    analysis_type = (analysis_type or "screenshot").strip().lower()
    if analysis_type not in {"screenshot", "ai_image"}:
        raise HTTPException(status_code=400, detail={"error": "analysis_type must be screenshot or ai_image"})
    try:
        if analysis_type == "ai_image":
            return run_ai_image_check(
                image_bytes,
                filename=image_file.filename or "",
                question=question,
                image_context=_parse_metadata_context(metadata_context),
            ).to_public_dict()
        return run_screenshot_factcheck(
            image_bytes,
            filename=image_file.filename or "",
            question=question,
        ).to_public_dict()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail={"error": str(exc)}) from exc
