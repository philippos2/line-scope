FROM python:3.14.4-slim AS base
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /workspace

FROM base AS builder
COPY backend/requirements.lock /tmp/requirements.lock
RUN pip install --no-cache-dir --prefix=/install -r /tmp/requirements.lock
COPY backend /workspace/backend
RUN pip wheel --no-deps --wheel-dir=/wheels /workspace/backend

FROM base AS runtime
COPY --from=builder /install /usr/local
COPY --from=builder /wheels /wheels
RUN pip install --no-deps --no-cache-dir /wheels/*.whl && rm -rf /wheels \
    && groupadd --gid 10001 linescope && useradd --uid 10001 --gid 10001 --no-create-home linescope
COPY scripts/container_health.py /workspace/container_health.py
USER 10001:10001
EXPOSE 8000
CMD ["linescope", "serve", "--host", "0.0.0.0", "--port", "8000"]

FROM runtime AS test
ENV RUFF_CACHE_DIR=/tmp/ruff-cache
USER root
COPY backend/requirements-dev.lock /tmp/requirements-dev.lock
RUN pip install --no-cache-dir -r /tmp/requirements-dev.lock
COPY --chown=10001:10001 backend /workspace/backend
COPY --chown=10001:10001 scripts /workspace/scripts
USER 10001:10001
CMD ["pytest", "backend/tests", "-q", "-p", "no:cacheprovider"]
