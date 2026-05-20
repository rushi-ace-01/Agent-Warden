FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY dashboard ./dashboard

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --target=/install ".[dashboard]"

FROM python:3.11-slim AS runtime

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.11/site-packages
COPY --from=builder /build/dashboard ./dashboard

USER 10001:10001

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8080/healthz').read()" || exit 1

ENTRYPOINT ["python", "-m", "uvicorn", "dashboard.app.main:app", "--host", "0.0.0.0", "--port", "8080"]
