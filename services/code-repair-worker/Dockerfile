# Build from the repository root; this is the trusted controller, not model tools.
FROM python:3.12-slim AS dependencies
COPY services/code-repair-worker/requirements.lock /build/requirements.lock
RUN python -m pip install --no-cache-dir --require-hashes --target /opt/dependencies -r /build/requirements.lock

FROM python:3.12-slim AS sandbox
COPY --from=dependencies /opt/dependencies /opt/dependencies
ENV PYTHONPATH=/opt/dependencies PYTHONDONTWRITEBYTECODE=1
# No Docker CLI/socket, credentials, sources or model client configuration.
WORKDIR /workspace
ENTRYPOINT ["sleep"]
CMD ["infinity"]

FROM sandbox AS controller
USER root
RUN apt-get update && apt-get install -y --no-install-recommends docker.io && rm -rf /var/lib/apt/lists/*
ENV OPENHANDS_SUPPRESS_BANNER=1 LITELLM_LOCAL_MODEL_COST_MAP=true OTEL_SDK_DISABLED=true CODE_REPAIR_BIND=0.0.0.0
COPY services/code-repair-worker/worker.py services/code-repair-worker/server.py /repo/services/code-repair-worker/
COPY ProjectServer/plane/quality/remote_source_snapshots.py /repo/ProjectServer/plane/quality/remote_source_snapshots.py
WORKDIR /repo
ENTRYPOINT ["python", "/repo/services/code-repair-worker/server.py"]
