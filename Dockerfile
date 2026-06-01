FROM python:3.11-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    FACTCHECK_AI_IMAGE_MODEL=metadata_only \
    FACTCHECK_NLI_MODEL=typeform/mobilebert-uncased-mnli \
    FACTCHECK_MAX_NLI_CALLS=6 \
    FACTCHECK_MAX_PASSAGES_PER_DOCUMENT=3

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 libglib2.0-0 libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.api.txt /app/requirements.api.txt
RUN pip install --no-cache-dir -r /app/requirements.api.txt

COPY . /app

EXPOSE 8001

CMD python -m uvicorn src.api_factcheck:app --host 0.0.0.0 --port ${PORT:-8001}
