FROM python:3.12.12-slim-bookworm@sha256:593bd06efe90efa80dc4eee3948be7c0fde4134606dd40d8dd8dbcade98e669c AS runtime-deps
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 OMP_NUM_THREADS=1 OPENBLAS_NUM_THREADS=1
WORKDIR /app
COPY requirements.lock .
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export PIP_CERT=/run/secrets/build_ca; fi; \
    pip install --no-cache-dir --require-hashes -r requirements.lock

FROM runtime-deps AS app
COPY models.json fetch_models.py ./
RUN --mount=type=secret,id=build_ca \
    if [ -f /run/secrets/build_ca ]; then export SSL_CERT_FILE=/run/secrets/build_ca; fi; \
    python fetch_models.py /opt/models
COPY licenses /licenses
COPY ringface ./ringface
LABEL io.hass.name="Ring Face Recognition" io.hass.description="Silent local visitor recognition" io.hass.type="addon" io.hass.version="0.1.3" io.hass.arch="amd64"
EXPOSE 8099
CMD ["python", "-m", "ringface"]
