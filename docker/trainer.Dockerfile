FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.lock pyproject.toml README.md ./
COPY src ./src
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock \
    && /opt/venv/bin/pip install --no-cache-dir --no-deps .

FROM python:3.12-slim AS runtime
ARG IMAGE_REVISION=local-dev
LABEL org.opencontainers.image.revision=$IMAGE_REVISION
ENV PATH=/opt/venv/bin:$PATH \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    TRAINING_ENVIRONMENT_VERSION=$IMAGE_REVISION
RUN groupadd --gid 10001 app && useradd --uid 10001 --gid app --create-home app \
    && mkdir -p /app/data /model-registry \
    && chown -R app:app /app /model-registry
COPY --from=builder /opt/venv /opt/venv
COPY data /app/data
COPY --chown=app:app requirements.lock /app/requirements.lock
COPY --chown=app:app alembic.ini /app/alembic.ini
COPY --chown=app:app migrations /app/migrations
RUN chmod -R a-w /app/data
USER 10001:10001
WORKDIR /app
VOLUME ["/model-registry"]
CMD ["train"]

