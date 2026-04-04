FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends git && rm -rf /var/lib/apt/lists/*

RUN git clone --depth 1 --branch v2026.4.3 https://github.com/NousResearch/hermes-agent.git /opt/hermes-agent && \
    cd /opt/hermes-agent && \
    pip install --no-cache-dir ".[all]" && \
    pip install --no-cache-dir aiohttp matrix-nio

ENV HERMES_HOME=/root/.hermes
WORKDIR /opt/hermes-agent

# Install hivemind plugin into both source and site-packages plugin directories
COPY hivemind/ /opt/hermes-agent/plugins/memory/hivemind/
COPY matrix_backend.py /opt/hermes-agent/matrix_backend.py

# hermes pip install puts plugins in site-packages — copy there too
RUN site=$(python3 -c "import sysconfig; print(sysconfig.get_path('purelib'))") && \
    cp -r /opt/hermes-agent/plugins/memory/hivemind "$site/plugins/memory/hivemind" && \
    cp /opt/hermes-agent/matrix_backend.py "$site/matrix_backend.py"

COPY skills/ /opt/hermes-agent/skills/introducer/

COPY agent-test/agent-entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
