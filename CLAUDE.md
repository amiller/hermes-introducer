# hermes-introducer

Cross-agent introduction service using Matrix protocol.

## Dev setup
```
docker compose up conduit -d        # Conduit on :6167 (default, simple registration)
# OR
docker compose --profile continuwuity up continuwuity -d  # Continuwuity on :6168 (24MB, more maintained)
pip install -r requirements.txt
python3 setup_users.py              # register test users on Conduit
pytest test_introducer.py -v        # run tests (requires Conduit running on :6167)
```

## Two servers available
- **Conduit** (:6167) — simple dummy auth registration, 114MB RAM, good for quick testing
- **Continuwuity** (:6168) — 24MB RAM, actively maintained, needs registration token (UIAA two-step flow)
- Tests currently target Conduit on :6167
- Continuwuity requires admin account creation on first boot (check `docker compose logs continuwuity` for initial token)

## Conventions
- Python 3.10+, async, matrix-nio for introducer, raw aiohttp for tests
- No fallbacks — propagate errors as-is
- Minimal code, prototype only
- Flat project structure, no packages
- matrix-nio join() doesn't work with Conduit (no JSON body sent) — tests use raw HTTP
