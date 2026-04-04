import pytest, pytest_asyncio, aiohttp, json, os, sys, uuid
from unittest.mock import patch, MagicMock
from introducer import MatrixIntroducer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hivemind import (
    HiveMindProvider, _run_async, _format_context,
    _maybe_update_and_spark, _update_spark_status,
    SUMMARY_KEY, SPARKS_KEY, ALL_TOOLS,
)
from matrix_backend import MatrixBackend

pytestmark = pytest.mark.asyncio


def _make_provider(user_id, access_token):
    """Create and initialize a provider outside the async test event loop."""
    provider = HiveMindProvider()
    with patch.dict(os.environ, {
        "MATRIX_HOMESERVER": HOMESERVER,
        "MATRIX_USER_ID": user_id,
        "MATRIX_ACCESS_TOKEN": access_token,
    }):
        provider.initialize(session_id="test")
    return provider

HOMESERVER = "http://localhost:6167"
PASSWORD = "testpass"


async def register_user(session, username):
    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.dummy"},
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


@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s


@pytest_asyncio.fixture
async def introduced(session):
    tag = uuid.uuid4().hex[:6]
    alice = await register_user(session, f"hm_alice_{tag}")
    bob = await register_user(session, f"hm_bob_{tag}")
    carol = await register_user(session, f"hm_carol_{tag}")

    alice_id, alice_tok = alice
    bob_id, bob_tok = bob
    carol_id, carol_tok = carol

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(
        bob_id, carol_id,
        "Bob builds DeFi protocols and needs a security audit",
        "Carol specializes in smart contract auditing",
    )
    await introducer.close()
    return {"alice": alice, "bob": bob, "carol": carol, "room_id": result["room_id"]}


# -- Unit tests (no Conduit needed for these) --

def test_tool_schemas_count():
    assert len(ALL_TOOLS) == 6
    names = {t["name"] for t in ALL_TOOLS}
    assert "hivemind_list_peers" in names
    assert "hivemind_introduce_peers" in names
    assert "hivemind_dismiss_spark" in names


def test_is_available_with_env():
    provider = HiveMindProvider()
    with patch.dict(os.environ, {
        "MATRIX_HOMESERVER": "http://localhost:6167",
        "MATRIX_USER_ID": "@test:localhost",
        "MATRIX_ACCESS_TOKEN": "tok",
    }):
        assert provider.is_available()


def test_is_available_without_env():
    provider = HiveMindProvider()
    with patch.dict(os.environ, {}, clear=True):
        assert not provider.is_available()


def test_format_context_empty():
    assert _format_context([], []) == ""


def test_format_context_peers_only():
    peers = [{"name": "carol", "introduced_by": "alice", "context": "Security researcher"}]
    result = _format_context(peers, [])
    assert "carol" in result
    assert "alice" in result
    assert "Suggestions" not in result


def test_format_context_with_suggestions():
    peers = [
        {"name": "bob", "introduced_by": "alice", "context": "DeFi dev"},
        {"name": "carol", "introduced_by": "alice", "context": "Auditor"},
    ]
    suggestions = [{"peer_a": "bob", "peer_b": "carol", "reason": "Match", "confidence": "high"}]
    result = _format_context(peers, suggestions)
    assert "Suggestions" in result
    assert "bob and carol" in result


def test_system_prompt_block():
    provider = HiveMindProvider()
    block = provider.system_prompt_block()
    assert "hivemind_list_peers" in block
    assert "hivemind_introduce_peers" in block


def test_get_tool_schemas():
    provider = HiveMindProvider()
    schemas = provider.get_tool_schemas()
    assert len(schemas) == 6
    assert all("name" in s and "parameters" in s for s in schemas)


# -- Integration tests (against live Conduit) --

async def test_initialize_creates_backend(introduced):
    bob_id, bob_tok = introduced["bob"]
    provider = _make_provider(bob_id, bob_tok)
    assert provider._backend is not None
    provider.shutdown()


async def test_prefetch_returns_peer_context(introduced):
    bob_id, bob_tok = introduced["bob"]
    provider = _make_provider(bob_id, bob_tok)
    result = provider.prefetch("who do I know?")
    carol_name = introduced["carol"][0].lstrip("@").split(":")[0]
    assert carol_name in result
    assert "Peers" in result
    provider.shutdown()


async def test_handle_list_peers(introduced):
    bob_id, bob_tok = introduced["bob"]
    provider = _make_provider(bob_id, bob_tok)
    result = json.loads(provider.handle_tool_call("hivemind_list_peers", {}))
    assert isinstance(result, list)
    assert len(result) >= 1
    carol_name = introduced["carol"][0].lstrip("@").split(":")[0]
    assert any(carol_name in p["name"] for p in result)
    provider.shutdown()


async def test_handle_send_to_peer(introduced, session):
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    room_id = introduced["room_id"]

    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers={"Authorization": f"Bearer {carol_tok}"}, json={},
    ) as resp:
        pass

    provider = _make_provider(bob_id, bob_tok)
    carol_name = carol_id.lstrip("@").split(":")[0]
    result = json.loads(provider.handle_tool_call(
        "hivemind_send_to_peer", {"peer": carol_name, "message": "Hello from plugin!"}
    ))
    assert result["sent"] is True

    carol_backend = MatrixBackend(HOMESERVER, carol_id, carol_tok)
    await carol_backend.get_peers()
    bob_name = bob_id.lstrip("@").split(":")[0]
    msgs = await carol_backend.get_messages_from_peer(bob_name)
    assert any("Hello from plugin" in m["text"] for m in msgs)
    await carol_backend.close()
    provider.shutdown()


async def test_handle_introduce_peers(introduced, session):
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    tag = uuid.uuid4().hex[:6]
    dave_id, dave_tok = await register_user(session, f"hm_dave_{tag}")

    alice_id, alice_tok = introduced["alice"]
    intro = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    await intro.introduce(bob_id, dave_id, "Bob does DeFi", "Dave does frontend")
    await intro.close()

    provider = _make_provider(bob_id, bob_tok)
    carol_name = carol_id.lstrip("@").split(":")[0]
    dave_name = dave_id.lstrip("@").split(":")[0]
    result = json.loads(provider.handle_tool_call(
        "hivemind_introduce_peers",
        {"peer_a": carol_name, "peer_b": dave_name, "reason": "Complementary skills"},
    ))
    assert result["introduced"] is True
    provider.shutdown()


async def test_dismiss_spark(introduced):
    bob_id, bob_tok = introduced["bob"]
    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok)
    try:
        await backend._put_global_account_data(SPARKS_KEY, {"sparks": [{
            "id": "test", "peer_a": "alice", "peer_b": "carol",
            "reason": "Test", "confidence": "high",
            "created_at": "2026-04-03T00:00:00Z", "status": "pending",
        }]})

        provider = _make_provider(bob_id, bob_tok)
        result = json.loads(provider.handle_tool_call(
            "hivemind_dismiss_spark", {"peer_a": "alice", "peer_b": "carol"}
        ))
        assert result["dismissed"] is True

        sparks = await backend._get_global_account_data(SPARKS_KEY)
        assert all(s["status"] == "dismissed" for s in sparks["sparks"])
        provider.shutdown()
    finally:
        await backend.close()
