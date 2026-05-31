# Verity Lens Render Deploy Config Verification

- Generated: `2026-05-31T12:21:37.525755+02:00`
- OK: `True`
- Service: `fake-news-detector-api`
- Runtime: `docker`
- Dockerfile path: `./Dockerfile`
- Health check path: `/health`
- Plan: `free`

## Checks

- `OK` render.yaml exists
- `OK` Dockerfile exists
- `OK` .dockerignore exists
- `OK` requirements.api.txt exists
- `OK` render.yaml parses as YAML (ok)
- `OK` render.yaml defines a web service
- `OK` Render service uses docker runtime
- `OK` Render service points to ./Dockerfile
- `OK` Render healthCheckPath is /health
- `OK` Render CORS env allows phone clients
- `OK` Render AI image model is metadata_only
- `OK` Render env FACTCHECK_MAX_SEARCH_RESULTS is numeric
- `OK` Render env FACTCHECK_MAX_DOCUMENTS is numeric
- `OK` Render env FACTCHECK_MAX_EVIDENCE is numeric
- `OK` Dockerfile uses python:3.11-slim
- `OK` Dockerfile installs requirements.api.txt
- `OK` Dockerfile uses API-only requirements
- `OK` Dockerfile copies deployment source into /app
- `OK` Dockerfile exposes fallback port 8001
- `OK` Dockerfile starts src.api_factcheck:app
- `OK` Dockerfile binds API to 0.0.0.0
- `OK` Dockerfile uses Render PORT with 8001 fallback
- `OK` requirements.api.txt includes beautifulsoup4
- `OK` requirements.api.txt includes fastapi
- `OK` requirements.api.txt includes numpy
- `OK` requirements.api.txt includes pillow
- `OK` requirements.api.txt includes python-multipart
- `OK` requirements.api.txt includes pyyaml
- `OK` requirements.api.txt includes rapidocr-onnxruntime
- `OK` requirements.api.txt includes requests
- `OK` requirements.api.txt includes uvicorn
- `OK` requirements.api.txt excludes desktop/training packages
- `OK` .dockerignore excludes .venv/
- `OK` .dockerignore excludes archive/
- `OK` .dockerignore excludes apps/
- `OK` .dockerignore excludes build/
- `OK` .dockerignore excludes dist/
- `OK` .dockerignore excludes docs/
- `OK` .dockerignore excludes outputs/
- `OK` .dockerignore excludes reports/
- `OK` .dockerignore excludes tests/
- `OK` .dockerignore excludes *.zip
- `OK` .dockerignore excludes *.apk
- `OK` .dockerignore excludes *.onnx

## Failures

- None

## Warnings

- Render plan is free; first request can be slow after sleep.
