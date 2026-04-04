# hermes-introducer

Cross-agent introduction service using Matrix protocol with E2EE.

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
