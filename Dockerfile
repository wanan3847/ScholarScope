FROM node:24-bookworm-slim AS frontend
WORKDIR /build
COPY frontend/package*.json frontend/
RUN npm ci --prefix frontend
COPY frontend frontend
COPY scripts/build_frontend.mjs scripts/build_frontend.mjs
RUN mkdir -p src/web/templates && node scripts/build_frontend.mjs

FROM python:3.14-slim-bookworm
ARG INCLUDE_EMBEDDINGS=0
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 \
    SCHOLARSCOPE_WORKSPACE_DIR=/data/workspace SCHOLARSCOPE_DATA_DIR=/data/runtime \
    SCHOLARSCOPE_DISABLE_EMBEDDINGS=1 MPLCONFIGDIR=/tmp/matplotlib \
    HF_HOME=/data/models
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates libgomp1 fonts-noto-cjk \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --uid 10001 --create-home researcher \
    && mkdir -p /data/workspace /data/runtime /data/models && chown -R researcher:researcher /data
RUN apt-get update && apt-get install -y --no-install-recommends poppler-utils tesseract-ocr tesseract-ocr-eng tesseract-ocr-chi-sim \
    && rm -rf /var/lib/apt/lists/*
COPY --from=frontend /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend /usr/local/LICENSE /usr/local/share/doc/node/LICENSE
COPY src/requirements.txt /tmp/requirements.txt
RUN if [ "$INCLUDE_EMBEDDINGS" = "1" ]; then \
      pip install --no-cache-dir torch --index-url https://download.pytorch.org/whl/cpu && pip install --no-cache-dir -r /tmp/requirements.txt; \
    else sed '/^sentence-transformers/d' /tmp/requirements.txt > /tmp/core.txt && pip install --no-cache-dir -r /tmp/core.txt; fi
ENV SCHOLARSCOPE_OCR_LANG=eng+chi_sim
WORKDIR /app
COPY src src
COPY scripts scripts
COPY --from=frontend /build/src/web/static src/web/static
COPY --from=frontend /build/src/web/templates src/web/templates
COPY --from=frontend /build/frontend/node_modules frontend/node_modules
USER researcher
WORKDIR /app/src
EXPOSE 8765
HEALTHCHECK --interval=30s --timeout=3s --start-period=40s CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8765/api/health', timeout=2)"
CMD ["python", "/app/scripts/container_start.py"]
