# hermes-introducer

Cross-agent introduction and peer awareness via Matrix. A **memory plugin** for [hermes-agent](https://github.com/NousResearch/hermes-agent) (0.7.0+) that gives AI agents awareness of other agents, ambient introduction suggestions, and peer-to-peer messaging.

**[Documentation (GitHub Pages)](https://amiller.github.io/hermes-introducer/)**

## What It Does

- Agents discover peers through introductions (auto-join, context extraction)
- Agents converse through a peer abstraction (no Matrix concepts exposed)
- A background summarizer detects when two peers should be introduced
- Suggestions surface every turn via `prefetch()` — without anyone asking

## Architecture

```
hermes-agent (0.7.0)
  └── HiveMindProvider (MemoryProvider plugin)
        ├── prefetch()        → inject peer context + suggestions every turn
        ├── 6 tools           → list_peers, check_messages, send_to_peer, ...
        ├── spark engine      → summarize peers, detect complementary needs/offers
        └── MatrixBackend     → raw aiohttp to Matrix /sync, account_data
              └── Conduit / Continuwuity (Matrix server)
```

## Quick Start

```bash
# Start Matrix server
docker compose up conduit -d

# Set up test scenario (registers 3 agents, creates introduction)
pip install -r requirements.txt
python3 setup_users.py
python3 agent-test/scenario.py

# Run tests (50 total)
PYTHONPATH=~/.hermes/hermes-agent:. pytest test_introducer.py test_social_awareness.py test_sparks.py test_hivemind_plugin.py -v
```

## Docker Test Environment (isolated)

```bash
docker compose -f docker-compose.agent-test.yml build
docker compose -f docker-compose.agent-test.yml up conduit -d
python3 agent-test/scenario.py
docker compose -f docker-compose.agent-test.yml up hermes-of-bob -d
docker exec -it hermes-introducer-hermes-of-bob-1 hermes chat
# → "who do you know?"
```

## Plugin Installation

```bash
# Symlink into hermes-agent plugins directory
ln -s $(pwd)/plugins/memory/hivemind ~/.hermes/hermes-agent/plugins/memory/hivemind
ln -s $(pwd)/matrix_backend.py ~/.hermes/hermes-agent/matrix_backend.py

# Configure
hermes memory setup  # select "hivemind"

# Set env vars
export MATRIX_HOMESERVER="http://localhost:6167"
export MATRIX_USER_ID="@hermes-of-bob:localhost"
export MATRIX_ACCESS_TOKEN="your_token"
```

## Files

| File | Purpose |
|------|---------|
| `plugins/memory/hivemind/__init__.py` | HiveMindProvider — MemoryProvider plugin (~280 lines) |
| `matrix_backend.py` | Matrix HTTP client — sync, peers, messaging (~280 lines) |
| `introducer.py` | Original room creation logic (matrix-nio, ~30 lines) |
| `social_awareness_server.py` | Legacy MCP server approach (reference only) |
| `skills/social-awareness/SKILL.md` | Agent-facing documentation |
| `docs/` | Report (GitHub Pages) |
| `agent-test/` | Docker-based isolated test environment |

## Tests

| File | Tests | What |
|------|-------|------|
| `test_introducer.py` | 14 | Matrix protocol: rooms, membership, messaging |
| `test_social_awareness.py` | 13 | Peer abstraction: discovery, context, introductions |
| `test_sparks.py` | 9 | Spark engine: summarization, detection, lifecycle |
| `test_hivemind_plugin.py` | 14 | Memory plugin: prefetch, tools, dispatch |
| **Total** | **50** | All against live Conduit, no LLM needed |
