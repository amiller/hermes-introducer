import pytest, pytest_asyncio, aiohttp, uuid
from introducer import MatrixIntroducer

pytestmark = pytest.mark.asyncio

HOMESERVER = "http://localhost:6167"
PASSWORD = "testpass"


# --- Matrix HTTP helpers (raw aiohttp, no matrix-nio for client ops) ---

async def register_user(session, username):
    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username,
        "password": PASSWORD,
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

def auth(token):
    return {"Authorization": f"Bearer {token}"}

async def join_room(session, token, room_id):
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/join/{room_id}",
        headers=auth(token), json={},
    ) as resp:
        return await resp.json()

async def leave_room(session, token, room_id):
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/leave",
        headers=auth(token), json={},
    ) as resp:
        return await resp.json()

async def invite_user(session, token, room_id, user_id):
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/invite",
        headers=auth(token), json={"user_id": user_id},
    ) as resp:
        return await resp.json()

async def kick_user(session, token, room_id, user_id, reason=""):
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/kick",
        headers=auth(token), json={"user_id": user_id, "reason": reason},
    ) as resp:
        return await resp.json()

async def ban_user(session, token, room_id, user_id, reason=""):
    async with session.post(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/ban",
        headers=auth(token), json={"user_id": user_id, "reason": reason},
    ) as resp:
        return await resp.json()

async def get_messages(session, token, room_id):
    async with session.get(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/messages",
        headers=auth(token), params={"dir": "b", "limit": "50"},
    ) as resp:
        data = await resp.json()
        assert "chunk" in data, f"messages failed: {data}"
        return [e["content"]["body"] for e in data["chunk"]
                if e.get("type") == "m.room.message"]

async def send_message(session, token, room_id, body):
    txn = uuid.uuid4().hex
    async with session.put(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
        headers=auth(token), json={"msgtype": "m.text", "body": body},
    ) as resp:
        data = await resp.json()
        assert "event_id" in data, f"send failed: {data}"
        return data

async def get_members(session, token, room_id):
    async with session.get(
        f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/members",
        headers=auth(token),
    ) as resp:
        data = await resp.json()
        return {e["state_key"]: e["content"]["membership"]
                for e in data.get("chunk", [])}


# --- Fixtures ---

@pytest_asyncio.fixture
async def session():
    async with aiohttp.ClientSession() as s:
        yield s

@pytest_asyncio.fixture
async def agents(session):
    tag = uuid.uuid4().hex[:6]
    alice = await register_user(session, f"alice_{tag}")
    bob = await register_user(session, f"bob_{tag}")
    carol = await register_user(session, f"carol_{tag}")
    return {"alice": alice, "bob": bob, "carol": carol}


# === HAPPY PATH ===

async def test_full_introduction_flow(agents, session):
    """Complete 3-agent flow: introduce, both join, exchange messages, verify all see everything."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(
        bob_id, carol_id,
        "Bob is a code reviewer who specializes in Rust",
        "Carol is a security researcher focused on TEE attestation",
        room_name="Introduction: Bob meets Carol",
    )
    await introducer.close()

    room_id = result["room_id"]
    assert room_id.startswith("!")
    assert set(result["invited"]) == {bob_id, carol_id}

    # Both agents join
    assert "room_id" in await join_room(session, bob_tok, room_id)
    assert "room_id" in await join_room(session, carol_tok, room_id)

    # Both see the intro context posted by alice
    bob_msgs = await get_messages(session, bob_tok, room_id)
    assert any("Bob" in m and "Rust" in m for m in bob_msgs)
    assert any("Carol" in m and "TEE" in m for m in bob_msgs)

    carol_msgs = await get_messages(session, carol_tok, room_id)
    assert any("Bob" in m and "Rust" in m for m in carol_msgs)
    assert any("Carol" in m and "TEE" in m for m in carol_msgs)

    # Agents exchange messages
    await send_message(session, bob_tok, room_id, "Hi Carol, I could use a security review on my Rust project")
    await send_message(session, carol_tok, room_id, "Happy to help Bob, send me the repo link")
    await send_message(session, bob_tok, room_id, "Great, here's the link: github.com/bob/project")

    # Both see the full conversation
    bob_msgs = await get_messages(session, bob_tok, room_id)
    assert any("security review" in m for m in bob_msgs)
    assert any("Happy to help" in m for m in bob_msgs)
    assert any("repo link" in m for m in bob_msgs)

    carol_msgs = await get_messages(session, carol_tok, room_id)
    assert any("security review" in m for m in carol_msgs)
    assert any("Happy to help" in m for m in carol_msgs)

    # All three are members
    members = await get_members(session, alice_tok, room_id)
    assert members[alice_id] == "join"
    assert members[bob_id] == "join"
    assert members[carol_id] == "join"


async def test_intro_context_visible_before_join(agents, session):
    """Messages posted by introducer are visible to agents who join later."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "context about bob", "context about carol")
    await introducer.close()
    room_id = result["room_id"]

    # Neither has joined yet — alice posts additional context
    await send_message(session, alice_tok, room_id, "You two should definitely connect about TEE research")

    # Bob joins much later and sees everything
    await join_room(session, bob_tok, room_id)
    msgs = await get_messages(session, bob_tok, room_id)
    assert any("context about bob" in m for m in msgs)
    assert any("context about carol" in m for m in msgs)
    assert any("TEE research" in m for m in msgs)


# === REJECTION / LEAVE EDGE CASES ===

async def test_agent_rejects_invite(agents, session):
    """Agent can reject invite by leaving before joining. Room continues for other agent."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    # Bob joins, carol rejects
    await join_room(session, bob_tok, room_id)
    await leave_room(session, carol_tok, room_id)  # reject = leave without joining

    members = await get_members(session, alice_tok, room_id)
    assert members[bob_id] == "join"
    assert members[carol_id] == "leave"

    # Bob can still use the room
    await send_message(session, bob_tok, room_id, "Guess it's just us, Alice")
    msgs = await get_messages(session, bob_tok, room_id)
    assert any("just us" in m for m in msgs)


async def test_rejected_agent_cannot_rejoin_invite_only(agents, session):
    """After rejecting an invite, agent cannot rejoin an invite-only room without re-invite."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    # Carol rejects
    await leave_room(session, carol_tok, room_id)

    # Carol tries to rejoin — should fail (invite-only room)
    resp = await join_room(session, carol_tok, room_id)
    assert "errcode" in resp  # M_FORBIDDEN


async def test_reinvite_after_rejection(agents, session):
    """Introducer can re-invite an agent who previously rejected."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    room_id = result["room_id"]

    # Carol rejects
    await leave_room(session, carol_tok, room_id)

    # Alice re-invites carol
    await invite_user(session, alice_tok, room_id, carol_id)

    # Now carol can join
    resp = await join_room(session, carol_tok, room_id)
    assert "room_id" in resp

    # Carol sees the original intro messages
    msgs = await get_messages(session, carol_tok, room_id)
    assert any("about bob" in m for m in msgs)
    await introducer.close()


async def test_agent_leaves_after_joining(agents, session):
    """Agent joins, participates, then leaves. Messages persist for remaining members."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)
    await join_room(session, carol_tok, room_id)

    await send_message(session, bob_tok, room_id, "Here's my analysis")
    await send_message(session, carol_tok, room_id, "Thanks, I'll review it")

    # Bob leaves
    await leave_room(session, bob_tok, room_id)

    # Carol still sees all messages
    msgs = await get_messages(session, carol_tok, room_id)
    assert any("analysis" in m for m in msgs)
    assert any("review" in m for m in msgs)

    # Bob cannot rejoin (invite-only)
    resp = await join_room(session, bob_tok, room_id)
    assert "errcode" in resp


async def test_both_agents_reject(agents, session):
    """Both introduced agents reject. Introducer is alone in the room."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await leave_room(session, bob_tok, room_id)
    await leave_room(session, carol_tok, room_id)

    members = await get_members(session, alice_tok, room_id)
    assert members[alice_id] == "join"
    assert members[bob_id] == "leave"
    assert members[carol_id] == "leave"

    # Alice (introducer) is still in the room and can send messages
    await send_message(session, alice_tok, room_id, "Nobody showed up")


# === ROOM DESTRUCTION / ABANDONMENT ===

async def test_introducer_leaves_room(agents, session):
    """Introducer leaves after introduction. Room continues for the other two agents."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)
    await join_room(session, carol_tok, room_id)

    # Introducer steps back
    await leave_room(session, alice_tok, room_id)

    # Bob and carol still interact
    await send_message(session, bob_tok, room_id, "Alice left, but we can keep talking")
    msgs = await get_messages(session, carol_tok, room_id)
    assert any("keep talking" in m for m in msgs)

    members = await get_members(session, bob_tok, room_id)
    assert members[alice_id] == "leave"
    assert members[bob_id] == "join"
    assert members[carol_id] == "join"


async def test_all_leave_room_becomes_unreachable(agents, session):
    """When everyone leaves an invite-only room, nobody can rejoin. Room is effectively dead."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)
    await leave_room(session, bob_tok, room_id)
    await leave_room(session, carol_tok, room_id)
    await leave_room(session, alice_tok, room_id)

    # Nobody can rejoin — room is abandoned
    resp = await join_room(session, alice_tok, room_id)
    assert "errcode" in resp
    resp = await join_room(session, bob_tok, room_id)
    assert "errcode" in resp


# === KICK / BAN ===

async def test_kick_agent_from_room(agents, session):
    """Introducer can kick a misbehaving agent. Kicked agent cannot rejoin without re-invite."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)
    await join_room(session, carol_tok, room_id)

    # Alice kicks bob
    await kick_user(session, alice_tok, room_id, bob_id, "misbehaving")

    members = await get_members(session, alice_tok, room_id)
    assert members[bob_id] == "leave"

    # Bob cannot rejoin
    resp = await join_room(session, bob_tok, room_id)
    assert "errcode" in resp

    # Re-invite allows rejoin
    await invite_user(session, alice_tok, room_id, bob_id)
    resp = await join_room(session, bob_tok, room_id)
    assert "room_id" in resp


async def test_ban_agent_from_room(agents, session):
    """Banned agent cannot rejoin even with re-invite."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)

    # Alice bans bob
    await ban_user(session, alice_tok, room_id, bob_id, "permanent removal")

    members = await get_members(session, alice_tok, room_id)
    assert members[bob_id] == "ban"

    # Bob cannot rejoin
    resp = await join_room(session, bob_tok, room_id)
    assert "errcode" in resp

    # Even re-invite fails for banned user
    resp = await invite_user(session, alice_tok, room_id, bob_id)
    assert "errcode" in resp


# === MESSAGE ORDERING / TIMING ===

async def test_message_ordering_preserved(agents, session):
    """Messages appear in the order they were sent."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    await join_room(session, bob_tok, room_id)
    await join_room(session, carol_tok, room_id)

    for i in range(5):
        await send_message(session, bob_tok, room_id, f"message-{i}")

    msgs = await get_messages(session, carol_tok, room_id)
    numbered = [m for m in msgs if m.startswith("message-")]
    # room_messages with dir=b returns newest first
    assert numbered == [f"message-{i}" for i in range(4, -1, -1)]


async def test_late_joiner_sees_all_history(agents, session):
    """An agent who joins much later sees the full room history including intro and conversation."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)
    result = await introducer.introduce(bob_id, carol_id, "about bob", "about carol")
    await introducer.close()
    room_id = result["room_id"]

    # Bob joins and has a conversation with alice
    await join_room(session, bob_tok, room_id)
    await send_message(session, alice_tok, room_id, "Bob, meet Carol when she arrives")
    await send_message(session, bob_tok, room_id, "Looking forward to it")

    # Carol joins much later
    await join_room(session, carol_tok, room_id)
    msgs = await get_messages(session, carol_tok, room_id)

    assert any("about bob" in m for m in msgs)
    assert any("about carol" in m for m in msgs)
    assert any("meet Carol" in m for m in msgs)
    assert any("Looking forward" in m for m in msgs)


# === MULTIPLE INTRODUCTIONS ===

async def test_multiple_introductions_create_separate_rooms(agents, session):
    """Multiple introductions between the same agents create distinct rooms."""
    alice_id, alice_tok = agents["alice"]
    bob_id, bob_tok = agents["bob"]
    carol_id, carol_tok = agents["carol"]

    introducer = MatrixIntroducer(HOMESERVER, alice_id, alice_tok)

    result1 = await introducer.introduce(bob_id, carol_id, "round 1 bob", "round 1 carol",
                                          room_name="First Introduction")
    result2 = await introducer.introduce(bob_id, carol_id, "round 2 bob", "round 2 carol",
                                          room_name="Second Introduction")
    await introducer.close()

    assert result1["room_id"] != result2["room_id"]

    await join_room(session, bob_tok, result1["room_id"])
    await join_room(session, bob_tok, result2["room_id"])

    msgs1 = await get_messages(session, bob_tok, result1["room_id"])
    msgs2 = await get_messages(session, bob_tok, result2["room_id"])

    assert any("round 1" in m for m in msgs1)
    assert not any("round 2" in m for m in msgs1)
    assert any("round 2" in m for m in msgs2)
    assert not any("round 1" in m for m in msgs2)
