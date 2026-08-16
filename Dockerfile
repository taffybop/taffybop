FROM python:3.13-slim-bookworm

ARG TORCH_VERSION=2.13.0
ARG TORCHVISION_VERSION=0.28.0

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libgl1 \
        libglib2.0-0 \
        libgomp1 \
        tesseract-ocr \
        tesseract-ocr-eng \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir \
        --index-url https://download.pytorch.org/whl/cpu \
        "torch==${TORCH_VERSION}" \
        "torchvision==${TORCHVISION_VERSION}" \
    && python -m pip install --no-cache-dir .

RUN mkdir -p /opt/docling-models \
    && docling-tools models download \
        layout \
        tableformer \
        picture_classifier \
        -o /opt/docling-models

# Generate only from the finished candidate image. The authoritative profile
# rejects missing dpkg copyright/file inventories, Python source/license
# metadata, model revisions/licenses, or changed bytes. Verification is local
# and performs no registry or hosted call.
RUN mkdir -p /app/release \
    && python -m app.services.artifact_manifest generate \
        --release-id document-parse-api-0.1.0-debian-bookworm \
        --candidate-root / \
        --output /app/release/shipped-artifacts.json \
        --digest-output /app/release/shipped-artifacts.sha256 \
    && python -m app.services.artifact_manifest verify \
        --manifest /app/release/shipped-artifacts.json \
        --expected-sha256-file /app/release/shipped-artifacts.sha256 \
        --candidate-root /

ENV DOCLING_ARTIFACTS_PATH=/opt/docling-models \
    HF_HUB_OFFLINE=1 \
    TRANSFORMERS_OFFLINE=1 \
    PARSER_RELEASE_ARTIFACT_MANIFEST_PATH=/app/release/shipped-artifacts.json \
    PARSER_RELEASE_ARTIFACT_ROOT=/ \
    PARSER_RELEASE_ARTIFACT_MANIFEST_DIGEST_PATH=/app/release/shipped-artifacts.sha256

EXPOSE 8000

CMD ["python", "-m", "app.release_start"]
