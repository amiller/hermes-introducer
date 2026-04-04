import pytest, pytest_asyncio, aiohttp, uuid, tempfile
from unittest.mock import AsyncMock, MagicMock
from datetime import datetime, timezone
from introducer import MatrixIntroducer
from matrix_backend import MatrixBackend
from social_awareness_server import (
    _summarize_peer, _detect_sparks, _maybe_update_and_spark,
    _update_spark_status, PeerSummary, SparkEvaluation,
    SUMMARY_KEY, SPARKS_KEY, STALENESS_THRESHOLD,
)
from conftest import HOMESERVER, register_user

pytestmark = pytest.mark.asyncio


def _mock_ctx_sample(return_value):
    ctx = MagicMock()
    result = MagicMock()
    result.result = return_value
    result.text = str(return_value)
    ctx.sample = AsyncMock(return_value=result)
    return ctx


# --- Summarization ---

async def test_summarize_peer_shape():
    summary = PeerSummary(
        needs=["security audit"], offers=["Rust development"],
        expertise=["smart contracts"], summary_text="Bob builds DeFi protocols",
    )
    ctx = _mock_ctx_sample(summary)
    result = await _summarize_peer(ctx, "bob", [{"from": "bob", "text": "hello"}], "Bob does Rust")
    assert result["needs"] == ["security audit"]
    assert result["offers"] == ["Rust development"]
    assert result["summary_text"] == "Bob builds DeFi protocols"
    ctx.sample.assert_called_once()


# --- Spark Detection ---

async def test_spark_detection_complementary():
    summaries = [
        {"peer_name": "bob", "needs": ["security audit"], "offers": ["Rust development"]},
        {"peer_name": "carol", "needs": ["Rust developer"], "offers": ["security auditing"]},
    ]
    eval_result = SparkEvaluation(should_introduce=True, reason="Bob needs audit, Carol offers it", confidence="high")
    ctx = _mock_ctx_sample(eval_result)
    sparks = await _detect_sparks(ctx, summaries)
    assert len(sparks) == 1
    assert sparks[0]["peer_a"] == "bob"
    assert sparks[0]["peer_b"] == "carol"
    assert sparks[0]["confidence"] == "high"


async def test_spark_detection_no_match():
    summaries = [
        {"peer_name": "bob", "needs": ["security audit"], "offers": ["Rust development"]},
        {"peer_name": "dave", "needs": ["recipe ideas"], "offers": ["cooking classes"]},
    ]
    eval_result = SparkEvaluation(should_introduce=False, reason="No overlap", confidence="low")
    ctx = _mock_ctx_sample(eval_result)
    sparks = await _detect_sparks(ctx, summaries)
    assert len(sparks) == 0


async def test_spark_detection_low_confidence_filtered():
    summaries = [
        {"peer_name": "bob", "needs": ["vague help"], "offers": ["general stuff"]},
        {"peer_name": "carol", "needs": ["something"], "offers": ["maybe"]},
    ]
    eval_result = SparkEvaluation(should_introduce=True, reason="Weak match", confidence="low")
    ctx = _mock_ctx_sample(eval_result)
    sparks = await _detect_sparks(ctx, summaries)
    assert len(sparks) == 0


# --- Full Spark Pipeline (against live Conduit) ---

@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s

@pytest_asyncio.fixture
async def three_peer_setup(session):
    """Alice introduces Bob↔Carol and Bob↔Dave. Returns backends and metadata."""
    tag = uuid.uuid4().hex[:6]
    alice = await register_user(session, f"sp_alice_{tag}")
    bob = await register_user(session, f"sp_bob_{tag}")
    carol = await register_user(session, f"sp_carol_{tag}")
    dave = await register_user(session, f"sp_dave_{tag}")

    alice_id, alice_tok = alice
    bob_id, bob_tok = bob
    carol_id, carol_tok = carol
    dave_id, dave_tok = dave

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    await introducer.introduce(bob_id, carol_id, "Bob does Rust", "Carol does security audits", encrypted=False)
    await introducer.introduce(bob_id, dave_id, "Bob does Rust", "Dave builds frontend UIs", encrypted=False)
    await introducer.close()

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    peers = await backend.get_peers()
    return {"backend": backend, "peers": peers, "bob": bob, "carol": carol, "dave": dave}


async def test_staleness_triggers_summarization(three_peer_setup):
    setup = three_peer_setup
    backend = setup["backend"]
    peers = setup["peers"]
    try:
        room_id = backend._resolve_peer(peers[0]["name"])
        summary = await backend._get_account_data(room_id, SUMMARY_KEY)
        assert summary is None  # confirms stale

        def make_result(*args, **kwargs):
            result = MagicMock()
            if "result_type" in kwargs and kwargs["result_type"] == SparkEvaluation:
                result.result = SparkEvaluation(
                    should_introduce=False, reason="No match", confidence="low",
                )
            else:
                result.result = PeerSummary(
                    needs=["audit"], offers=["Rust"], expertise=["DeFi"], summary_text="Test peer",
                )
            return result

        ctx = MagicMock()
        ctx.sample = AsyncMock(side_effect=make_result)

        await _maybe_update_and_spark(ctx, backend, peers)
        assert ctx.sample.call_count >= 1

        summary = await backend._get_account_data(room_id, SUMMARY_KEY)
        assert summary is not None
        assert summary["peer_name"] == peers[0]["name"]
    finally:
        await backend.close()


async def test_sparks_stored_in_global_account_data(three_peer_setup):
    setup = three_peer_setup
    backend = setup["backend"]
    peers = setup["peers"]
    try:
        # First call: summarize returns needs/offers, spark eval returns True
        call_count = 0
        def make_result(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            result = MagicMock()
            if "result_type" in kwargs and kwargs["result_type"] == SparkEvaluation:
                result.result = SparkEvaluation(
                    should_introduce=True,
                    reason="Complementary skills",
                    confidence="high",
                )
            else:
                result.result = PeerSummary(
                    needs=["audit"], offers=["frontend"],
                    expertise=["DeFi"], summary_text="Test",
                )
            return result

        ctx = MagicMock()
        ctx.sample = AsyncMock(side_effect=make_result)

        await _maybe_update_and_spark(ctx, backend, peers)

        sparks_data = await backend._get_global_account_data(SPARKS_KEY)
        assert sparks_data is not None
        pending = [s for s in sparks_data["sparks"] if s["status"] == "pending"]
        assert len(pending) >= 1
        assert pending[0]["reason"] == "Complementary skills"
    finally:
        await backend.close()


async def test_sparks_deduplicated(three_peer_setup):
    setup = three_peer_setup
    backend = setup["backend"]
    peers = setup["peers"]
    try:
        # Manually store a spark
        await backend._put_global_account_data(SPARKS_KEY, {"sparks": [{
            "id": "existing",
            "peer_a": peers[0]["name"], "peer_b": peers[1]["name"],
            "reason": "Already suggested",
            "confidence": "high",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }]})

        def make_result(*args, **kwargs):
            result = MagicMock()
            if "result_type" in kwargs and kwargs["result_type"] == SparkEvaluation:
                result.result = SparkEvaluation(
                    should_introduce=True, reason="Same pair again", confidence="high",
                )
            else:
                result.result = PeerSummary(
                    needs=["x"], offers=["y"], expertise=["z"], summary_text="T",
                )
            return result

        ctx = MagicMock()
        ctx.sample = AsyncMock(side_effect=make_result)

        await _maybe_update_and_spark(ctx, backend, peers)

        sparks_data = await backend._get_global_account_data(SPARKS_KEY)
        pair = tuple(sorted([peers[0]["name"], peers[1]["name"]]))
        matching = [s for s in sparks_data["sparks"]
                    if tuple(sorted([s["peer_a"], s["peer_b"]])) == pair]
        assert len(matching) == 1, f"Expected 1 spark for pair, got {len(matching)}"
    finally:
        await backend.close()


async def test_dismiss_spark(three_peer_setup):
    setup = three_peer_setup
    backend = setup["backend"]
    peers = setup["peers"]
    try:
        await backend._put_global_account_data(SPARKS_KEY, {"sparks": [{
            "id": "to_dismiss",
            "peer_a": peers[0]["name"], "peer_b": peers[1]["name"],
            "reason": "Test", "confidence": "high",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }]})

        await _update_spark_status(backend, peers[0]["name"], peers[1]["name"], "dismissed")

        sparks_data = await backend._get_global_account_data(SPARKS_KEY)
        pending = [s for s in sparks_data["sparks"] if s["status"] == "pending"]
        assert len(pending) == 0
        dismissed = [s for s in sparks_data["sparks"] if s["status"] == "dismissed"]
        assert len(dismissed) == 1
    finally:
        await backend.close()


async def test_executed_spark_status(three_peer_setup):
    setup = three_peer_setup
    backend = setup["backend"]
    peers = setup["peers"]
    try:
        await backend._put_global_account_data(SPARKS_KEY, {"sparks": [{
            "id": "to_execute",
            "peer_a": peers[0]["name"], "peer_b": peers[1]["name"],
            "reason": "Good match", "confidence": "high",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "status": "pending",
        }]})

        await _update_spark_status(backend, peers[0]["name"], peers[1]["name"], "executed")

        sparks_data = await backend._get_global_account_data(SPARKS_KEY)
        executed = [s for s in sparks_data["sparks"] if s["status"] == "executed"]
        assert len(executed) == 1
        assert executed[0]["reason"] == "Good match"
    finally:
        await backend.close()
