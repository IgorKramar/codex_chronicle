# syntax=docker/dockerfile:1
FROM python:3.12-slim
WORKDIR /app
COPY pyproject.toml requirements-server.lock ./
COPY src ./src
RUN --mount=type=secret,id=proxy_ca \
    if [ -f /run/secrets/proxy_ca ]; then export PIP_CERT=/run/secrets/proxy_ca; fi; \
    pip install --no-cache-dir -r requirements-server.lock && pip install --no-cache-dir --no-deps .
COPY --chmod=0644 deploy/entrypoint.py /app/deploy/entrypoint.py
RUN useradd --uid 10001 --create-home chronicle && mkdir /data && chown chronicle /data && chmod 755 /app /app/deploy
USER chronicle
ENV CHRONICLE_STATE_DIR=/data PYTHONDONTWRITEBYTECODE=1
EXPOSE 8787
CMD ["python", "-m", "uvicorn", "chronicle.collector:create_app", "--factory", "--host", "0.0.0.0", "--port", "8787", "--no-access-log"]
