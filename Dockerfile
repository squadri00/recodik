# syntax=docker/dockerfile:1

# --- build stage: resolve dependencies into wheels ---------------------------
FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt

# --- runtime stage ---------------------------------------------------------
FROM python:3.12-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    MYVAULT_HOST=0.0.0.0 \
    MYVAULT_PORT=8000 \
    MYVAULT_DB=/data/myvault.sqlite3

RUN useradd --system --create-home --uid 1000 myvault \
 && mkdir -p /data && chown myvault:myvault /data

WORKDIR /app
COPY --from=builder /wheels /wheels
COPY requirements.txt .
RUN pip install --no-cache-dir --no-index --find-links=/wheels -r requirements.txt \
 && rm -rf /wheels

COPY myvault/ ./myvault/
COPY serve.py ./

USER myvault
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=3s --start-period=5s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/login').status==200 else 1)"

CMD ["python", "serve.py"]
