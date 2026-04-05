#!/usr/bin/env python3
"""
End-to-end tests for the hivemind plugin with real LLM inference.

Requires:
  - docker compose agent-test env running (continuwuity + honcho + agents)
  - ZAI_API_KEY set in agent-test/.env
  - HERMES_SECRET_KEY set for notebook tests

Run:
  # Start services
  docker compose -f docker-compose.agent-test.yml build
  docker compose -f docker-compose.agent-test.yml up continuwuity honcho-api honcho-db honcho-redis -d
  python3 agent-test/scenario.py
  docker compose -f docker-compose.agent-test.yml --env-file agent-test/.env.agents up -d

  # Run tests
  python3 agent-test/test_e2e.py
"""
import asyncio, aiohttp, json, os, subprocess, sys, tempfile, time, uuid
import urllib.request, urllib.parse

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:6167")
HONCHO_URL = os.environ.get("HONCHO_BASE_URL", "http://localhost:8000")
HERMES_URL = os.environ.get("HERMES_URL", "https://hermes.teleport.computer")
HERMES_KEY = os.environ.get("HERMES_SECRET_KEY", "")
PASSWORD = "testpass"
TOKEN = os.environ.get("MATRIX_REGISTRATION_TOKEN", "agent-dev")

BOB_CONTAINER = "hermes-introducer-hermes-of-bob-1"

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


# ---- Helpers ----

def container_running(name):
    r = subprocess.run(["docker", "inspect", "-f", "{{.State.Running}}", name],
                       capture_output=True, text=True)
    return r.stdout.strip() == "true"


total_estimated_tokens = 0

def hermes_query(container, message, timeout=120):
    """Send a single message to hermes-agent and return the response text.

    Token counting: hermes-agent doesn't expose per-request token usage.
    We estimate ~4 chars/token from the session file (system prompt + tools + messages).
    For precise counting, options:
      - Add a lightweight HTTP proxy between the agent and ZAI that logs response.usage
      - Patch hermes-agent to write usage.prompt_tokens / usage.completion_tokens to session JSON
      - Use the ZAI billing dashboard to check actual usage after a test run
    """
    global total_estimated_tokens
    r = subprocess.run(
        ["docker", "exec", container, "hermes", "chat", "--query", message, "--quiet"],
        capture_output=True, text=True, timeout=timeout,
    )
    lines = r.stdout.strip().split("\n")
    response_lines = []
    session_id = None
    for line in lines:
        if line.startswith("session_id:"):
            session_id = line.split(":", 1)[1].strip()
        else:
            response_lines.append(line)
    response = "\n".join(response_lines).strip()
    # Rough estimate: ~16k tokens for system prompt + tools, plus message content
    est = 16000 + len(message) // 4 + len(response) // 4
    total_estimated_tokens += est
    return {
        "response": response,
        "session_id": session_id,
        "exit_code": r.returncode,
        "stderr": r.stderr,
        "estimated_tokens": est,
    }


# ---- Service health ----

def check_service(name, url, check):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=5) as resp:
            data = json.loads(resp.read())
            report(f"{name} reachable", check(data))
    except Exception as e:
        report(f"{name} reachable", False, str(e))


def check_agent_container():
    ok = container_running(BOB_CONTAINER)
    report("bob agent container running", ok,
           "start with: docker compose -f docker-compose.agent-test.yml --env-file agent-test/.env.agents up -d")
    return ok


# ---- Matrix E2EE (no LLM) ----

async def test_e2ee_roundtrip():
    """Create encrypted intro room, verify peer discovery and message delivery."""
    from introducer import MatrixIntroducer
    from matrix_backend import MatrixBackend

    tag = uuid.uuid4().hex[:6]
    async with aiohttp.ClientSession() as session:
        async def reg(u):
            async with session.post(f"{HOMESERVER}/_matrix/client/v3/register",
                                    json={"username": u, "password": PASSWORD}) as r:
                d = await r.json()
                if "access_token" in d: return d["user_id"], d["access_token"]
                s = d.get("session", "")
            async with session.post(f"{HOMESERVER}/_matrix/client/v3/register",
                                    json={"username": u, "password": PASSWORD,
                                          "auth": {"type": "m.login.registration_token",
                                                   "token": TOKEN, "session": s}}) as r:
                d = await r.json()
                return d["user_id"], d["access_token"]

        alice_id, alice_tok = await reg(f"e2e_a_{tag}")
        bob_id, bob_tok = await reg(f"e2e_b_{tag}")
        carol_id, carol_tok = await reg(f"e2e_c_{tag}")

    intro = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await intro.introduce(bob_id, carol_id, "Bob does ML", "Carol does infra", encrypted=True)
    await intro.close()
    report("E2EE room created", bool(result["room_id"]))

    bob_backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    peers = await bob_backend.get_peers()
    carol_name = carol_id.lstrip("@").split(":")[0]
    report("peer discovery works", any(carol_name in p["name"] for p in peers))

    await bob_backend.send_to_peer(carol_name, "E2EE test message")
    carol_backend = MatrixBackend(HOMESERVER, carol_id, carol_tok, store_path=tempfile.mkdtemp())
    await carol_backend.get_peers()
    bob_name = bob_id.lstrip("@").split(":")[0]
    msgs = await carol_backend.get_messages_from_peer(bob_name)
    report("E2EE message delivery", any("E2EE test" in m["text"] for m in msgs))

    await bob_backend.close()
    await carol_backend.close()


# ---- Notebook search (no LLM) ----

def test_notebook_search():
    if not HERMES_KEY:
        report("notebook search", False, "HERMES_SECRET_KEY not set")
        return
    params = urllib.parse.urlencode({"q": "matrix", "limit": 2, "key": HERMES_KEY})
    url = f"{HERMES_URL}/api/search?{params}"
    req = urllib.request.Request(url, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=5) as resp:
        data = json.loads(resp.read())
    results = data.get("results", [])
    has_content = any(r.get("content") for r in results)
    report("notebook search returns content", has_content,
           f"{len(results)} results, content lengths: {[len(r.get('content','')) for r in results]}")


# ---- LLM-backed tests (require running agent container + ZAI key) ----

def test_llm_peer_awareness():
    """Agent should know about carol (introduced peer) without being told."""
    result = hermes_query(BOB_CONTAINER, "Do you know any other agents or peers? List them if so.")
    resp = result["response"].lower()
    report("LLM responds successfully", result["exit_code"] == 0 and len(result["response"]) > 10,
           f"exit={result['exit_code']}, len={len(result['response'])}, stderr={result['stderr'][:200]}")
    report("LLM mentions carol (peer awareness)",
           "carol" in resp,
           f"response: {result['response'][:300]}")


def test_llm_notebook_ambient():
    """Agent should reference notebook content as ambient context, not as user-provided."""
    result = hermes_query(BOB_CONTAINER,
        "What do you know about introduction graphs or agent introductions? "
        "Don't search or use tools, just tell me what context you already have.")
    resp = result["response"].lower()

    # Should reference the topic (notebook has entries about introduction graphs)
    has_topic = any(w in resp for w in ["introduction", "graph", "peer", "matrix", "trust"])
    report("LLM has ambient notebook context", has_topic,
           f"response: {result['response'][:300]}")

    # Should NOT say "you shared" / "you pasted" / "you provided"
    bad_attributions = ["you shared", "you pasted", "you provided", "you mentioned",
                        "you sent", "your message contain", "from your input"]
    misattributed = any(phrase in resp for phrase in bad_attributions)
    report("LLM does not misattribute notebook as user input", not misattributed,
           f"found bad attribution in: {result['response'][:300]}")


def test_llm_no_hallucinated_context():
    """On an unrelated query, the agent shouldn't inject notebook content unprompted."""
    result = hermes_query(BOB_CONTAINER, "What is 7 times 8?")
    resp = result["response"].lower()
    report("LLM answers simple math", "56" in resp,
           f"response: {result['response'][:200]}")
    # Should not randomly bring up introduction graphs or notebook entries
    notebook_leak = any(w in resp for w in ["introduction graph", "notebook entries",
                                             "ambient context", "hermes notebook"])
    report("LLM doesn't leak notebook context on unrelated query", not notebook_leak,
           f"response: {result['response'][:200]}")


# ---- Main ----

async def main():
    print("=" * 60)
    print("Hivemind E2E Tests (with LLM)")
    print("=" * 60)

    print("\n--- Service Health ---")
    check_service("continuwuity", f"{HOMESERVER}/_matrix/client/versions",
                  lambda d: "versions" in d)
    check_service("honcho API", f"{HONCHO_URL}/openapi.json",
                  lambda d: True)
    agent_up = check_agent_container()

    print("\n--- Matrix E2EE (no LLM) ---")
    await test_e2ee_roundtrip()

    print("\n--- Notebook Search (no LLM) ---")
    test_notebook_search()

    if not agent_up:
        print("\n--- LLM Tests SKIPPED (agent container not running) ---")
    else:
        print("\n--- LLM: Peer Awareness ---")
        test_llm_peer_awareness()

        print("\n--- LLM: Notebook Ambient Context ---")
        test_llm_notebook_ambient()

        print("\n--- LLM: No Hallucinated Context ---")
        test_llm_no_hallucinated_context()

    print(f"\n{'=' * 60}")
    print(f"Results: {passed} passed, {failed} failed")
    if total_estimated_tokens:
        print(f"Estimated LLM tokens: ~{total_estimated_tokens:,}")
    print(f"{'=' * 60}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    asyncio.run(main())
