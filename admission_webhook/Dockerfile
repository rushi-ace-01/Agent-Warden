FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY admission_webhook ./admission_webhook
COPY guardrails_service ./guardrails_service

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --target=/install ".[admission-webhook]" && \
    pip install --no-cache-dir --target=/install kubernetes

FROM python:3.11-slim AS runtime

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.11/site-packages
COPY --from=builder /build/admission_webhook ./admission_webhook

USER 10001:10001

EXPOSE 8443

ENV TLS_CERT_PATH=/tls/tls.crt
ENV TLS_KEY_PATH=/tls/tls.key

ENTRYPOINT ["sh", "-c", "exec python -m uvicorn admission_webhook.app.main:app --host 0.0.0.0 --port 8443 --ssl-certfile ${TLS_CERT_PATH} --ssl-keyfile ${TLS_KEY_PATH}"]
