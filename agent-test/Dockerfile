FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v2026.4.3 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \
    cd /opt/hermes-agent && \
    pip install --no-cache-dir -e ".[all]" && \
    pip install --no-cache-dir fastmcp aiohttp matrix-nio

ENV HERMES_HOME=/root/.hermes
ENV PATH="/opt/hermes-agent/venv/bin:$PATH"
WORKDIR /opt/hermes-agent

COPY skills/ /opt/hermes-agent/skills/introducer/
COPY social_awareness_server.py matrix_backend.py introducer.py /opt/
COPY agent-test/agent-entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
