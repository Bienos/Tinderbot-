# syntax=docker/dockerfile:1
# One customer's bot on a small Fly.io machine. Slim on purpose: the Tinder connector is plain HTTP, so no browser.
FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 PIP_DISABLE_PIP_VERSION_CHECK=1 PORT=8080
WORKDIR /app
COPY requirements.lock .
# Playwright (a browser, ~165 MB) only serves the local simulator; customers' bots never load it.
# Optional build secret "pip_ca": a CA bundle for builds behind a TLS-inspecting proxy. Unused on Fly.
RUN --mount=type=secret,id=pip_ca,required=false \
    if [ -f /run/secrets/pip_ca ]; then export PIP_CERT=/run/secrets/pip_ca; fi; \
    grep -v '^playwright==' requirements.lock > /tmp/requirements.txt && \
    pip install -r /tmp/requirements.txt && useradd --create-home --uid 10001 agent
COPY app.py ./
COPY agent ./agent
COPY static ./static
COPY data ./data
COPY deploy/fly/entrypoint.sh /usr/local/bin/entrypoint
COPY deploy/fly/serve.py /app/serve.py
RUN chmod 0755 /usr/local/bin/entrypoint
EXPOSE 8080
ENTRYPOINT ["/usr/local/bin/entrypoint"]
