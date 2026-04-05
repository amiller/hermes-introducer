import pytest, pytest_asyncio, aiohttp, uuid, tempfile
from introducer import MatrixIntroducer
from matrix_backend import MatrixBackend
from conftest import HOMESERVER, register_user

pytestmark = pytest.mark.asyncio

async def send_message(session, token, room_id, body):
    txn = uuid.uuid4().hex
    async with session.put(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
        headers={"Authorization": f"Bearer {token}"}, json={"msgtype": "m.text", "body": body},
    ) as resp:
        data = await resp.json()
        assert "event_id" in data, f"send failed: {data}"


# --- Fixtures ---

@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s

@pytest_asyncio.fixture
async def agents(session):
    tag = uuid.uuid4().hex[:6]
    alice = await register_user(session, f"sa_alice_{tag}")
    bob = await register_user(session, f"sa_bob_{tag}")
    carol = await register_user(session, f"sa_carol_{tag}")
    return {"alice": alice, "bob": bob, "carol": carol}

@pytest_asyncio.fixture
async def introduced(agents, session):
    """Alice introduces Bob ↔ Carol, returns room_id + agent info."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(
        bob_id, carol_id,
        "Bob is a Rust developer who reviews smart contracts",
        "Carol specializes in TEE attestation and security audits",
        room_name="Test Introduction",
        encrypted=True,
    )
    await introducer.close()
    return {**agents, "room_id": result["room_id"]}


# === ITERATION 1: PASSIVE AWARENESS ===

async def test_auto_join_and_discover_peer(introduced):
    """Bob syncs, auto-joins the invite, discovers Carol as a peer."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, _ = introduced["carol"]

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        assert len(peers) >= 1, f"Expected at least 1 peer, got {peers}"
        carol_peer = next(p for p in peers if carol_id.lstrip("@").split(":")[0] in p["name"])
        assert "TEE attestation" in carol_peer["context"]
        assert carol_peer["status"] == "active"
    finally:
        await backend.close()


async def test_peer_context_extracted(introduced):
    """The introduction context about each peer is correctly extracted."""
    carol_id, carol_tok = introduced["carol"]
    bob_id, _ = introduced["bob"]

    backend = MatrixBackend(HOMESERVER, carol_id, carol_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        bob_peer = next(p for p in peers if bob_id.lstrip("@").split(":")[0] in p["name"])
        assert "Rust developer" in bob_peer["context"]
        assert "smart contracts" in bob_peer["context"]
    finally:
        await backend.close()


async def test_introduced_by_is_alice(introduced):
    """The introducer (Alice) is recorded."""
    bob_id, bob_tok = introduced["bob"]
    alice_id, _ = introduced["alice"]

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        assert len(peers) >= 1
        alice_name = alice_id.lstrip("@").split(":")[0]
        assert peers[0]["introduced_by"] == alice_name
    finally:
        await backend.close()


async def test_peer_id_format(introduced):
    """Peer ID is opaque (no @ prefix, no : separator visible)."""
    bob_id, bob_tok = introduced["bob"]

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        assert len(peers) >= 1
        peer_id = peers[0]["id"]
        assert not peer_id.startswith("@"), f"Peer ID should not start with @: {peer_id}"
        assert ":" not in peer_id.split("@")[0], f"Peer ID format wrong: {peer_id}"
    finally:
        await backend.close()


async def test_check_messages_from_peer(introduced, session):
    """Messages in the room appear as peer messages."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    room_id = introduced["room_id"]

    # Carol joins and sends a message
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers={"Authorization": f"Bearer {carol_tok}"}, json={},
    ) as resp:
        assert (await resp.json()).get("room_id")

    await send_message(session, carol_tok, room_id, "Hey Bob, happy to help with your audit!")

    # Bob discovers Carol, then checks messages
    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        carol_name = carol_id.lstrip("@").split(":")[0]
        messages = await backend.get_messages_from_peer(carol_name)
        bodies = [m["text"] for m in messages]
        assert any("happy to help" in b for b in bodies), f"Expected Carol's message, got: {bodies}"
        assert all("from" in m and "text" in m and "time" in m for m in messages)
    finally:
        await backend.close()


async def test_no_matrix_ids_in_messages(introduced, session):
    """Message 'from' field uses names, not Matrix IDs."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    room_id = introduced["room_id"]

    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers={"Authorization": f"Bearer {carol_tok}"}, json={},
    ) as resp:
        pass

    await send_message(session, carol_tok, room_id, "Test message")

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        await backend.get_peers()
        carol_name = carol_id.lstrip("@").split(":")[0]
        messages = await backend.get_messages_from_peer(carol_name)
        for m in messages:
            assert not m["from"].startswith("@"), f"Matrix ID leaked: {m['from']}"
    finally:
        await backend.close()


async def test_multiple_introductions(agents, session):
    """Two separate introductions create two separate peers."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    # Register a 4th user
    tag = uuid.uuid4().hex[:6]
    dave_id, dave_tok = await register_user(session, f"sa_dave_{tag}")

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    await introducer.introduce(bob_id, carol_id, "Bob does Rust", "Carol does security", encrypted=True)
    await introducer.introduce(bob_id, dave_id, "Bob does Rust", "Dave does frontend", encrypted=True)
    await introducer.close()

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        assert len(peers) >= 2, f"Expected 2+ peers, got {peers}"
        names = {p["name"] for p in peers}
        carol_name = carol_id.lstrip("@").split(":")[0]
        dave_name = dave_id.lstrip("@").split(":")[0]
        assert carol_name in names, f"Missing Carol in {names}"
        assert dave_name in names, f"Missing Dave in {names}"
    finally:
        await backend.close()


async def test_get_peer_info(introduced):
    """get_peer_info returns full details for a specific peer."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, _ = introduced["carol"]

    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        peers = await backend.get_peers()
        carol_name = carol_id.lstrip("@").split(":")[0]
        carol_peer = next(p for p in peers if p["name"] == carol_name)
        assert carol_peer["context"] != ""
        assert carol_peer["introduced_by"] != ""
        assert carol_peer["introduced_at"] != ""
        assert carol_peer["status"] == "active"
    finally:
        await backend.close()


# === ITERATION 2: ACTIVE COMMUNICATION ===

async def test_send_to_peer(introduced, session):
    """Bob sends a message to Carol via send_to_peer."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    room_id = introduced["room_id"]

    # Carol joins
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers={"Authorization": f"Bearer {carol_tok}"}, json={},
    ) as resp:
        pass

    # Bob discovers Carol, then sends
    bob_backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    carol_backend = MatrixBackend(HOMESERVER, carol_id, carol_tok, store_path=tempfile.mkdtemp())
    try:
        await bob_backend.get_peers()
        carol_name = carol_id.lstrip("@").split(":")[0]
        await bob_backend.send_to_peer(carol_name, "Can you review my contract?")

        # Carol sees Bob's message
        await carol_backend.get_peers()
        bob_name = bob_id.lstrip("@").split(":")[0]
        messages = await carol_backend.get_messages_from_peer(bob_name)
        bodies = [m["text"] for m in messages]
        assert any("review my contract" in b for b in bodies), f"Bob's message not found: {bodies}"
    finally:
        await bob_backend.close()
        await carol_backend.close()


# === ITERATION 2.5: INTRODUCE_PEERS ===

async def test_introduce_peers_creates_room(agents, session):
    """Bob introduces Carol ↔ Dave via create_introduction_room."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]
    tag = uuid.uuid4().hex[:6]
    dave_id, dave_tok = await register_user(session, f"sa_dave_{tag}")

    # Alice introduces Bob↔Carol and Bob↔Dave
    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    await introducer.introduce(bob_id, carol_id, "Bob does Rust", "Carol does security", encrypted=True)
    await introducer.introduce(bob_id, dave_id, "Bob does Rust", "Dave does frontend", encrypted=True)
    await introducer.close()

    # Bob discovers peers, then introduces Carol↔Dave
    bob_b = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        await bob_b.get_peers()
        meta_c = bob_b.get_peer_meta(carol_id.lstrip("@").split(":")[0])
        meta_d = bob_b.get_peer_meta(dave_id.lstrip("@").split(":")[0])
        assert meta_c and meta_d

        result = await bob_b.create_introduction_room(
            meta_c["peer_id"], meta_d["peer_id"],
            "Carol does security audits", "Dave builds frontend UIs",
            reason="Carol needs a frontend for her audit dashboard",
        )
        assert "room_id" in result
        assert carol_id in result["invited"]
        assert dave_id in result["invited"]
    finally:
        await bob_b.close()


async def test_introduce_peers_posts_context(agents, session):
    """Introduction room contains About messages for both peers."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]
    tag = uuid.uuid4().hex[:6]
    dave_id, dave_tok = await register_user(session, f"sa_dave_{tag}")

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    await introducer.introduce(bob_id, carol_id, "Bob does Rust", "Carol does security", encrypted=True)
    await introducer.introduce(bob_id, dave_id, "Bob does Rust", "Dave does frontend", encrypted=True)
    await introducer.close()

    bob_b = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        await bob_b.get_peers()
        meta_c = bob_b.get_peer_meta(carol_id.lstrip("@").split(":")[0])
        meta_d = bob_b.get_peer_meta(dave_id.lstrip("@").split(":")[0])

        result = await bob_b.create_introduction_room(
            meta_c["peer_id"], meta_d["peer_id"],
            "Carol does security audits", "Dave builds frontend UIs",
            reason="Complementary skills",
        )

        # Read messages from the new room
        messages = await bob_b._get_messages(result["room_id"], limit=10)
        bodies = [m.get("content", {}).get("body", "") for m in messages if m.get("type") == "m.room.message"]
        assert any("About" in b and "Carol" in b for b in bodies), f"Missing Carol context: {bodies}"
        assert any("About" in b and "Dave" in b for b in bodies), f"Missing Dave context: {bodies}"
        assert any("Why:" in b for b in bodies), f"Missing reason: {bodies}"
    finally:
        await bob_b.close()


async def test_global_account_data(agents):
    """Global account_data (user-level) round-trips correctly."""
    bob_id, bob_tok = agents["bob"]
    backend = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    try:
        test_key = f"test.global.{uuid.uuid4().hex[:6]}"
        await backend._put_global_account_data(test_key, {"hello": "world"})
        result = await backend._get_global_account_data(test_key)
        assert result == {"hello": "world"}
    finally:
        await backend.close()


async def test_bidirectional_conversation(introduced, session):
    """Bob and Carol exchange messages through peer abstraction."""
    bob_id, bob_tok = introduced["bob"]
    carol_id, carol_tok = introduced["carol"]
    room_id = introduced["room_id"]

    # Carol joins
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers={"Authorization": f"Bearer {carol_tok}"}, json={},
    ) as resp:
        pass

    bob_b = MatrixBackend(HOMESERVER, bob_id, bob_tok, store_path=tempfile.mkdtemp())
    carol_b = MatrixBackend(HOMESERVER, carol_id, carol_tok, store_path=tempfile.mkdtemp())
    try:
        await bob_b.get_peers()
        await carol_b.get_peers()

        carol_name = carol_id.lstrip("@").split(":")[0]
        bob_name = bob_id.lstrip("@").split(":")[0]

        await bob_b.send_to_peer(carol_name, "Hello Carol!")
        await carol_b.send_to_peer(bob_name, "Hi Bob!")
        await bob_b.send_to_peer(carol_name, "How's the audit going?")

        msgs = await carol_b.get_messages_from_peer(bob_name)
        bob_texts = [m["text"] for m in msgs if m["from"] == bob_name]
        assert len(bob_texts) >= 2
    finally:
        await bob_b.close()
        await carol_b.close()
