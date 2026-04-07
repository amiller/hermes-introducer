# hermes-introducer

Cross-agent introduction service using Matrix protocol with E2EE.

**Status: archived POC.** Active development moved to `Account-Link/dev-router-matrix` (private). This repo is kept public as a standalone proof of concept.

## Related repos
| Repo | Visibility | Purpose |
|---|---|---|
| `amiller/hermes-introducer` | public (archived) | This one — standalone hivemind/introduction POC |
| `Account-Link/dev-router-matrix` | private | Teleport Router product (live CVM, MCP bot) |
| `amiller/dstack-matrix` | public | Clean example of Matrix on TEE |

## Hivemind plugin
The `hivemind/` directory is symlinked into hermes-agent at `~/.hermes/hermes-agent/plugins/memory/hivemind`. It provides the `MemoryProvider` that reads/writes notebook entries via Matrix.

## Dev setup
```
docker compose up continuwuity -d   # Continuwuity on :6167
pip install -r requirements.txt     # matrix-nio[e2e] + libolm
python3 setup_users.py              # register test users (two-step UIAA, token: agent-dev)
pytest tests/ -v                    # run tests (requires Continuwuity on :6167)
```

## First boot
Continuwuity generates a bootstrap registration token on first start.
Check `docker compose logs continuwuity` for it, register the first account,
then the config token (`agent-dev`) works for subsequent registrations.

## Conventions
- Python 3.10+, async, matrix-nio[e2e] for all Matrix operations
- E2EE enabled: rooms created with m.room.encryption, messages auto-encrypted
- No fallbacks — propagate errors as-is
- Minimal code, prototype only
- Flat project structure, no packages
- Continuwuity as the Matrix server (Conduit removed — nio join() didn't work with it)
