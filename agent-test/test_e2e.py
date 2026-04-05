#!/usr/bin/env python3
"""
End-to-end test for hivemind plugin: Matrix E2EE + notebook search + honcho.

Requires:
  - Continuwuity on :6167
  - Honcho API on :8100
  - Hermes notebook API at hermes.teleport.computer (or HERMES_URL)

Run: python3 agent-test/test_e2e.py
"""
import asyncio, aiohttp, json, os, sys, tempfile, uuid, urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:6167")
HONCHO_URL = os.environ.get("HONCHO_BASE_URL", "http://localhost:8100")
HERMES_URL = os.environ.get("HERMES_URL", "https://hermes.teleport.computer")
HERMES_KEY = os.environ.get("HERMES_SECRET_KEY", "")
PASSWORD = "testpass"
TOKEN = os.environ.get("MATRIX_REGISTRATION_TOKEN", "agent-dev")

passed = 0
failed = 0


def report(name, ok, detail=""):
    global passed, failed
    if ok:
        passed += 1
        print(f"  PASS  {name}")
    else:
        failed += 1
        print(f"  FAIL  {name}: {detail}")


async def register(session, username):
    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        if "access_token" in data:
            return data["user_id"], data["access_token"]
        uiaa_session = data.get("session", "")

    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.registration_token", "token": TOKEN, "session": uiaa_session},
    }) as resp:
        data = await resp.json()
        if "access_token" in data:
            return data["user_id"], data["access_token"]

    async with session.post(f"{HOMESERVER}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        assert "access_token" in data, f"login failed: {data}"
        return data["user_id"], data["access_token"]


# ---- Service health checks ----

async def check_continuwuity(session):
    try:
        async with session.get(f"{HOMESERVER}/_matrix/client/versions") as resp:
            data = await resp.json()
            report("continuwuity reachable", "versions" in data)
    except Exception as e:
        report("continuwuity reachable", False, str(e))


async def check_honcho(session):
    try:
        async with session.get(f"{HONCHO_URL}/openapi.json") as resp:
            report("honcho API reachable", resp.status == 200)
    except Exception as e:
        report("honcho API reachable", False, str(e))


def check_notebook():
    try:
        params = urllib.parse.urlencode({"q": "test", "limit": 1})
        url = f"{HERMES_URL}/api/search?{params}"
        req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            report("notebook API reachable", "results" in data or isinstance(data, list))
    except Exception as e:
        report("notebook API reachable", False, str(e))


# ---- Matrix E2EE tests ----

async def test_e2ee_introduction(session):
    """Create encrypted intro room, verify peers can read messages via MatrixBackend."""
    from introducer import MatrixIntroducer
    from matrix_backend import MatrixBackend

    tag = uuid.uuid4().hex[:6]
    alice_id, alice_tok = await register(session, f"e2e_alice_{tag}")
    bob_id, bob_tok = await register(session, f"e2e_bob_{tag}")
    carol_id, carol_tok = await register(session, f"e2e_carol_{tag}")

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(
        bob_id, carol_id,
        "Bob builds distributed systems",
        "Carol does cryptography research",
        encrypted=True,
    )
    room_id = result["room_id"]
    await introducer.close()
    report("E2EE room created", bool(room_id))

    # Bob joins and reads via MatrixBackend (crypto-enabled)
    bob_backend = MatrixBackend(HOMESERVER, bob_id, bob_tok,
                                store_path=tempfile.mkdtemp())
    peers = await bob_backend.get_peers()
    carol_name = carol_id.lstrip("@").split(":")[0]
    peer_names = [p["name"] for p in peers]
    report("bob discovers carol as peer", carol_name in peer_names)

    # Bob sends encrypted message to carol
    await bob_backend.send_to_peer(carol_name, "Hello from E2EE test!")

    # Carol reads it
    carol_backend = MatrixBackend(HOMESERVER, carol_id, carol_tok,
                                  store_path=tempfile.mkdtemp())
    await carol_backend.get_peers()
    bob_name = bob_id.lstrip("@").split(":")[0]
    msgs = await carol_backend.get_messages_from_peer(bob_name)
    has_msg = any("Hello from E2EE" in m["text"] for m in msgs)
    report("carol reads bob's E2EE message", has_msg,
           f"got {len(msgs)} msgs: {[m['text'][:50] for m in msgs]}")

    await bob_backend.close()
    await carol_backend.close()
    return {"bob": (bob_id, bob_tok), "carol": (carol_id, carol_tok), "room_id": room_id}


# ---- Notebook search tests ----

def test_notebook_search():
    """Search notebook API with auth key, verify content returned."""
    params = urllib.parse.urlencode({"q": "matrix", "limit": 3, "key": HERMES_KEY})
    url = f"{HERMES_URL}/api/search?{params}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    results = data.get("results", [])
    report("notebook search returns results", len(results) > 0)
    has_content = any(r.get("content") for r in results)
    report("notebook entries have content (auth works)", has_content,
           f"got {len(results)} results, content lengths: {[len(r.get('content','')) for r in results]}")


# ---- Honcho API tests ----

async def test_honcho_workspace(session):
    """Create workspace and peer via honcho API, verify round-trip."""
    # Create workspace
    async with session.post(f"{HONCHO_URL}/v3/workspaces", json={
        "name": "hivemind-e2e-test",
    }) as resp:
        if resp.status in (200, 201):
            ws = await resp.json()
            ws_id = ws.get("id") or ws.get("workspace_id")
            report("honcho create workspace", bool(ws_id))
        elif resp.status == 409:
            # Already exists, fetch it
            async with session.get(f"{HONCHO_URL}/v3/workspaces?name=hivemind-e2e-test") as r2:
                data = await r2.json()
                items = data if isinstance(data, list) else data.get("items", [data])
                ws_id = items[0].get("id") if items else None
                report("honcho workspace exists", bool(ws_id))
        else:
            body = await resp.text()
            report("honcho create workspace", False, f"status={resp.status}: {body}")
            return

    # Create peer
    async with session.post(f"{HONCHO_URL}/v3/workspaces/{ws_id}/peers", json={
        "name": "e2e-test-peer",
    }) as resp:
        if resp.status in (200, 201):
            peer = await resp.json()
            peer_id = peer.get("id") or peer.get("peer_id")
            report("honcho create peer", bool(peer_id))
        else:
            body = await resp.text()
            report("honcho create peer", False, f"status={resp.status}: {body}")
            return

    # Create session
    sess_key = f"e2e-{uuid.uuid4().hex[:8]}"
    async with session.post(f"{HONCHO_URL}/v3/workspaces/{ws_id}/sessions", json={
        "id": sess_key,
        "peers": {peer_id: {"name": "e2e-test-peer"}},
    }) as resp:
        if resp.status in (200, 201):
            sess = await resp.json()
            sess_id = sess.get("id", sess_key)
            report("honcho create session", bool(sess_id))
        else:
            body = await resp.text()
            report("honcho create session", False, f"status={resp.status}: {body}")
            return

    # Add messages (batch format)
    async with session.post(
        f"{HONCHO_URL}/v3/workspaces/{ws_id}/sessions/{sess_id}/messages",
        json={"messages": [
            {"peer_id": peer_id, "content": "What is E2EE?", "role": "user"},
            {"peer_id": peer_id, "content": "End-to-end encryption.", "role": "ai"},
        ]},
    ) as resp:
        if resp.status in (200, 201):
            report("honcho add messages", True)
        else:
            body = await resp.text()
            report("honcho add messages", False, f"status={resp.status}: {body}")

    # Get peer card (simpler endpoint to verify round-trip)
    async with session.get(f"{HONCHO_URL}/v3/workspaces/{ws_id}/peers/{peer_id}/card") as resp:
        if resp.status == 200:
            data = await resp.json()
            report("honcho get peer card", True)
        else:
            body = await resp.text()
            report("honcho get peer card", False, f"status={resp.status}: {body}")


# ---- Hivemind plugin integration ----

def test_hivemind_prefetch_all_sources():
    """Test that prefetch() combines Matrix peers + notebook + honcho context.

    Runs synchronously (no outer async loop) because the hivemind plugin uses
    its own background event loop via _run_async, which deadlocks if called
    from within another asyncio.run().
    """
    import types
    if "agent" not in sys.modules:
        agent_mod = types.ModuleType("agent")
        mp_mod = types.ModuleType("agent.memory_provider")
        class MemoryProvider:
            def is_available(self): return False
            def initialize(self, session_id, **kw): pass
            def system_prompt_block(self): return ""
            def prefetch(self, query, **kw): return ""
            def get_tool_schemas(self): return []
            def handle_tool_call(self, name, args, **kw): return "{}"
            def shutdown(self): pass
        mp_mod.MemoryProvider = MemoryProvider
        agent_mod.memory_provider = mp_mod
        sys.modules["agent"] = agent_mod
        sys.modules["agent.memory_provider"] = mp_mod

    import hivemind
    hivemind.HERMES_SECRET_KEY = HERMES_KEY
    hivemind.HERMES_NOTEBOOK_URL = HERMES_URL
    from hivemind import HiveMindProvider, _run_async

    # Register users synchronously via _run_async (same background loop the plugin uses)
    tag = uuid.uuid4().hex[:6]

    async def _register_users():
        async with aiohttp.ClientSession() as s:
            alice = await register(s, f"hm_alice_{tag}")
            bob = await register(s, f"hm_bob_{tag}")
            carol = await register(s, f"hm_carol_{tag}")
            return alice, bob, carol

    (alice_id, alice_tok), (bob_id, bob_tok), (carol_id, carol_tok) = _run_async(_register_users())

    async def _do_intro():
        from introducer import MatrixIntroducer
        intro = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
        await intro.introduce(bob_id, carol_id, "Bob does ML", "Carol does infra", encrypted=True)
        await intro.close()

    _run_async(_do_intro())

    os.environ["MATRIX_HOMESERVER"] = HOMESERVER
    os.environ["MATRIX_USER_ID"] = bob_id
    os.environ["MATRIX_ACCESS_TOKEN"] = bob_tok
    os.environ["HERMES_HOME"] = tempfile.mkdtemp()

    provider = HiveMindProvider()
    provider.initialize(session_id="e2e-test")
    report("hivemind initializes with Matrix backend", provider._backend is not None)

    result = provider.prefetch("matrix federation encryption")
    has_peers = "Peers" in result
    has_notebook = "Notebook" in result
    report("prefetch includes Matrix peers", has_peers, f"result length={len(result)}")
    report("prefetch includes notebook entries", has_notebook)

    # Tool call: list peers
    carol_name = carol_id.lstrip("@").split(":")[0]
    try:
        peers_json = provider.handle_tool_call("hivemind_list_peers", {})
        peers = json.loads(peers_json)
        report("hivemind_list_peers returns carol", any(carol_name in p["name"] for p in peers))
    except Exception as e:
        report("hivemind_list_peers returns carol", False, f"{type(e).__name__}: {e}")

    # Send E2EE message via tool
    try:
        send_result = provider.handle_tool_call(
            "hivemind_send_to_peer", {"peer": carol_name, "message": "E2E test msg"})
        report("hivemind_send_to_peer E2EE works", json.loads(send_result).get("sent"))
    except Exception as e:
        report("hivemind_send_to_peer E2EE works", False, f"{type(e).__name__}: {e}")

    provider.shutdown()


async def main():
    print("=" * 60)
    print("Hivemind E2E Tests")
    print("=" * 60)

    async with aiohttp.ClientSession() as session:
        print("\n--- Service Health ---")
        await check_continuwuity(session)
        await check_honcho(session)
        check_notebook()

        print("\n--- Matrix E2EE ---")
        await test_e2ee_introduction(session)

        print("\n--- Notebook Search ---")
        test_notebook_search()

        print("\n--- Honcho API ---")
        await test_honcho_workspace(session)

    print("\n--- Hivemind Plugin (all sources) ---")
    test_hivemind_prefetch_all_sources()

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
