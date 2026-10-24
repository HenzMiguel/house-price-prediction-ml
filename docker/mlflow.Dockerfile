FROM python:3.12-slim AS builder
WORKDIR /build
COPY requirements.lock ./
RUN python -m venv /opt/venv \
    && /opt/venv/bin/pip install --no-cache-dir --upgrade pip \
    && /opt/venv/bin/pip install --no-cache-dir --require-hashes -r requirements.lock

FROM python:3.12-slim
ENV PATH=/opt/venv/bin:$PATH PYTHONUNBUFFERED=1
RUN groupadd --gid 10002 mlflow && useradd --uid 10002 --gid mlflow --create-home mlflow \
    && mkdir -p /mlflow-artifacts && chown mlflow:mlflow /mlflow-artifacts
COPY --from=builder /opt/venv /opt/venv
USER 10002:10002
EXPOSE 5000
VOLUME ["/mlflow-artifacts"]
ENTRYPOINT ["mlflow", "server"]
CMD ["--host", "0.0.0.0", "--port", "5000", "--serve-artifacts"]

