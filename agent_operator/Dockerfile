FROM python:3.11-slim AS builder

WORKDIR /build

COPY pyproject.toml ./
COPY agent_operator ./agent_operator

RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir --target=/install ".[operator]"

FROM python:3.11-slim AS runtime

RUN groupadd --gid 10001 app && \
    useradd --uid 10001 --gid app --no-create-home --shell /sbin/nologin app

WORKDIR /app

COPY --from=builder /install /usr/local/lib/python3.11/site-packages
COPY --from=builder /install/bin/kopf /usr/local/bin/kopf
COPY --from=builder /build/agent_operator ./agent_operator

USER 10001:10001

ENTRYPOINT ["kopf", "run", "--standalone", "-A", "agent_operator.scoped_agent.handlers"]
