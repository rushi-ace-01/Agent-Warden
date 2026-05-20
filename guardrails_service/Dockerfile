FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY guardrails_service ./guardrails_service

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --target=/install ".[guardrails-service]"

FROM python:3.11-slim AS runtime

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.11/site-packages
COPY --from=builder /build/guardrails_service ./guardrails_service

USER 10001:10001

EXPOSE 8000

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz').read()" || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "guardrails_service.app.main:app", "--host", "0.0.0.0", "--port", "8000"]
