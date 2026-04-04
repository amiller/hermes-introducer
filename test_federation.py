import asyncio, aiohttp, json, sys, uuid

HS_A = "http://localhost:6170"  # server-a client API
HS_B = "http://localhost:6171"  # server-b client API
PASSWORD = "testpass"

async def register(s, hs, username, bootstrap_token, config_token):
    # Bootstrap admin if needed
    async with s.post(f"{hs}/_matrix/client/v3/register", json={
        "username": "admin", "password": "admin",
    }) as r:
        d = await r.json()
        session = d.get("session", "")
    async with s.post(f"{hs}/_matrix/client/v3/register", json={
        "username": "admin", "password": "admin",
        "auth": {"type": "m.login.registration_token", "token": bootstrap_token, "session": session},
    }) as r:
        await r.json()

    # Register user
    async with s.post(f"{hs}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
    }) as r:
        d = await r.json()
        session = d.get("session", "")
    async with s.post(f"{hs}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.registration_token", "token": config_token, "session": session},
    }) as r:
        d = await r.json()
        if "access_token" in d:
            return d["user_id"], d["access_token"]
    async with s.post(f"{hs}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": PASSWORD,
    }) as r:
        d = await r.json()
        assert "access_token" in d, f"login failed: {d}"
        return d["user_id"], d["access_token"]

def auth(tok):
    return {"Authorization": f"Bearer {tok}"}

async def main():
    bootstrap_a, bootstrap_b = sys.argv[1], sys.argv[2]

    async with aiohttp.ClientSession() as s:
        alice_id, alice_tok = await register(s, HS_A, "alice", bootstrap_a, "token-a")
        bob_id, bob_tok = await register(s, HS_B, "bob", bootstrap_b, "token-b")
        carol_id, carol_tok = await register(s, HS_B, "carol", bootstrap_b, "token-b")
        print(f"Alice: {alice_id} (server-a)")
        print(f"Bob:   {bob_id} (server-b)")
        print(f"Carol: {carol_id} (server-b)")

        # Check signing keys
        for label, hs in [("A", HS_A), ("B", HS_B)]:
            async with s.get(f"{hs}/_matrix/key/v2/server") as r:
                d = await r.json()
                print(f"Server {label} keys: {list(d.get('verify_keys', {}).keys())}, name: {d.get('server_name')}")

        # === CROSS-SERVER INTRODUCTION ===
        print(f"\n{'='*50}")
        print("Cross-server introduction: Alice@A introduces Bob@B and Carol@B")
        print(f"{'='*50}")

        # Alice creates room on server-a and invites bob@server-b and carol@server-b
        async with s.post(f"{HS_A}/_matrix/client/v3/createRoom",
            headers=auth(alice_tok),
            json={"name": "Federated Introduction", "invite": [bob_id, carol_id]}) as r:
            d = await r.json()
            assert "room_id" in d, f"create failed: {d}"
            room_id = d["room_id"]
            print(f"\n1. Room created: {room_id}")

        # Alice posts intro context
        for msg in ["About Bob: distributed systems engineer at server-b",
                     "About Carol: cryptography researcher at server-b"]:
            txn = uuid.uuid4().hex
            async with s.put(f"{HS_A}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
                headers=auth(alice_tok), json={"msgtype": "m.text", "body": msg}) as r:
                await r.json()
        print("2. Alice posted intro context")

        # Wait for federation propagation
        await asyncio.sleep(2)

        # Bob checks for invite via sync on server-b
        async with s.get(f"{HS_B}/_matrix/client/v3/sync",
            headers=auth(bob_tok), params={"timeout": "5000"}) as r:
            sync = await r.json()
            invites = sync.get("rooms", {}).get("invite", {})
            print(f"3. Bob's pending invites: {list(invites.keys())}")
            if room_id in invites:
                invite_state = invites[room_id].get("invite_state", {}).get("events", [])
                for ev in invite_state:
                    if ev.get("type") == "m.room.name":
                        print(f"   Room name: {ev['content']['name']}")
                    if ev.get("type") == "m.room.member" and ev["content"].get("membership") == "invite":
                        print(f"   Invited by: {ev.get('sender')}")

        # Bob joins from server-b
        async with s.post(f"{HS_B}/_matrix/client/v3/join/{room_id}",
            headers=auth(bob_tok), json={}) as r:
            d = await r.json()
            assert "room_id" in d, f"bob join failed: {d}"
            print(f"4. Bob joined from server-b")

        # Carol checks and joins
        async with s.get(f"{HS_B}/_matrix/client/v3/sync",
            headers=auth(carol_tok), params={"timeout": "5000"}) as r:
            sync = await r.json()
            invites = sync.get("rooms", {}).get("invite", {})

        async with s.post(f"{HS_B}/_matrix/client/v3/join/{room_id}",
            headers=auth(carol_tok), json={}) as r:
            d = await r.json()
            assert "room_id" in d, f"carol join failed: {d}"
            print(f"5. Carol joined from server-b")

        # Bob reads messages (from server-b, fetched via federation)
        async with s.get(f"{HS_B}/_matrix/client/v3/rooms/{room_id}/messages",
            headers=auth(bob_tok), params={"dir": "b", "limit": "20"}) as r:
            msgs = await r.json()
            bodies = [e["content"]["body"] for e in msgs.get("chunk", []) if e.get("type") == "m.room.message"]
            print(f"6. Bob sees messages: {bodies}")

        # Bob sends a reply (from server-b, federated back to server-a)
        txn = uuid.uuid4().hex
        async with s.put(f"{HS_B}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
            headers=auth(bob_tok), json={"msgtype": "m.text", "body": "Hi Carol, nice to meet you!"}) as r:
            d = await r.json()
            assert "event_id" in d, f"bob send failed: {d}"
            print("7. Bob sent reply from server-b")

        await asyncio.sleep(1)

        # Carol reads (also from server-b)
        async with s.get(f"{HS_B}/_matrix/client/v3/rooms/{room_id}/messages",
            headers=auth(carol_tok), params={"dir": "b", "limit": "20"}) as r:
            msgs = await r.json()
            bodies = [e["content"]["body"] for e in msgs.get("chunk", []) if e.get("type") == "m.room.message"]
            print(f"8. Carol sees messages: {bodies}")

        # Alice reads from server-a (should see bob's message via federation)
        async with s.get(f"{HS_A}/_matrix/client/v3/rooms/{room_id}/messages",
            headers=auth(alice_tok), params={"dir": "b", "limit": "20"}) as r:
            msgs = await r.json()
            bodies = [e["content"]["body"] for e in msgs.get("chunk", []) if e.get("type") == "m.room.message"]
            print(f"9. Alice sees messages (including Bob's federated reply): {bodies}")

        # Check members from both servers
        async with s.get(f"{HS_A}/_matrix/client/v3/rooms/{room_id}/members",
            headers=auth(alice_tok)) as r:
            d = await r.json()
            members = {e["state_key"]: e["content"]["membership"] for e in d.get("chunk", [])}
            print(f"\n10. Room members (from server-a view): {json.dumps(members, indent=4)}")

        print(f"\n{'='*50}")
        print("FEDERATION TEST COMPLETE")
        print(f"{'='*50}")

asyncio.run(main())
