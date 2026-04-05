import pytest, pytest_asyncio, aiohttp, json, os, sys, uuid, tempfile
from unittest.mock import patch, MagicMock
from introducer import MatrixIntroducer

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from hivemind import (
    HiveMindProvider, _run_async, _format_context,
    _maybe_update_and_spark, _update_spark_status,
    SUMMARY_KEY, SPARKS_KEY, ALL_TOOLS,
)
from matrix_backend import MatrixBackend
from conftest import HOMESERVER, register_user

pytestmark = pytest.mark.asyncio


def _make_provider(user_id, access_token):
    provider = HiveMindProvider()
    with patch.dict(os.environ, {
        "MATRIX_HOMESERVER": HOMESERVER,
        "MATRIX_USER_ID": user_id,
        "MATRIX_ACCESS_TOKEN": access_token,
    }):
        provider.initialize(session_id="test")
    return provider


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
        encrypted=True,
    )
    await introducer.close()
    return {"alice": alice, "bob": bob, "carol": carol, "room_id": result["room_id"]}


# -- Integration tests (E2EE, against live Continuwuity) --

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
    assert "peer" in result.lower()
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
    await intro.introduce(bob_id, dave_id, "Bob does DeFi", "Dave does frontend", encrypted=True)
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
    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
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


# -- Notebook search (requires HERMES_SECRET_KEY) --

def _get_test_key():
    key = os.environ.get("HERMES_SECRET_KEY", "")
    if not key:
        pytest.skip("HERMES_SECRET_KEY not set")
    return key


def test_search_notebook_returns_content():
    from hivemind import _search_notebook
    import hivemind
    old_key = hivemind.HERMES_SECRET_KEY
    hivemind.HERMES_SECRET_KEY = _get_test_key()
    try:
        results = _search_notebook("matrix", limit=1)
        assert len(results) > 0
        assert results[0].get("content"), "Expected non-empty content with secret key"
    finally:
        hivemind.HERMES_SECRET_KEY = old_key


def test_prefetch_notebook_only():
    """Provider without Matrix should still return notebook context."""
    provider = HiveMindProvider()
    import hivemind
    old_key = hivemind.HERMES_SECRET_KEY
    hivemind.HERMES_SECRET_KEY = _get_test_key()
    try:
        with patch.dict(os.environ, {}, clear=True):
            provider.initialize(session_id="test")
        assert provider._backend is None
        result = provider.prefetch("matrix federation")
        assert "notebook entries" in result
    finally:
        hivemind.HERMES_SECRET_KEY = old_key


# -- Honcho routing --

def test_honcho_tool_routing():
    """honcho_* tools route to honcho delegate, hivemind_* without backend fails."""
    provider = HiveMindProvider()
    mock_honcho = MagicMock()
    mock_honcho.handle_tool_call.return_value = '{"result": "test"}'
    provider._honcho = mock_honcho
    result = provider.handle_tool_call("honcho_profile", {})
    assert json.loads(result)["result"] == "test"

    provider2 = HiveMindProvider()
    with pytest.raises(AssertionError, match="Matrix backend not configured"):
        provider2.handle_tool_call("hivemind_list_peers", {})
