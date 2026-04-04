import asyncio, aiohttp, json, time, subprocess

HS = "http://localhost:6167"
PASSWORD = "testpass"
CONTAINER = "hermes-introducer-conduit-1"

def mem_mb():
    out = subprocess.check_output(
        ["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", CONTAINER],
        text=True,
    ).strip()
    return out.split("/")[0].strip()

async def register(s, username):
    async with s.post(f"{HS}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.dummy"},
    }) as r:
        d = await r.json()
        if "access_token" in d:
            return d["user_id"], d["access_token"]
    async with s.post(f"{HS}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": PASSWORD,
    }) as r:
        d = await r.json()
        assert "access_token" in d, f"login {username} failed: {d}"
        return d["user_id"], d["access_token"]

def auth(tok):
    return {"Authorization": f"Bearer {tok}"}

async def create_room(s, tok, name, invite=None):
    body = {"name": name}
    if invite:
        body["invite"] = invite
    async with s.post(f"{HS}/_matrix/client/v3/createRoom", headers=auth(tok), json=body) as r:
        d = await r.json()
        assert "room_id" in d, f"create_room failed: {d}"
        return d["room_id"]

async def send_msg(s, tok, room_id, body, txn):
    async with s.put(
        f"{HS}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
        headers=auth(tok), json={"msgtype": "m.text", "body": body},
    ) as r:
        return await r.json()

async def join(s, tok, room_id):
    async with s.post(f"{HS}/_matrix/client/v3/join/{room_id}", headers=auth(tok), json={}) as r:
        return await r.json()

async def sync_once(s, tok):
    async with s.get(f"{HS}/_matrix/client/v3/sync", headers=auth(tok), params={"timeout": "0"}) as r:
        d = await r.json()
        return d.get("next_batch", "")

async def long_poll(s, tok, since, timeout_ms=30000):
    async with s.get(f"{HS}/_matrix/client/v3/sync", headers=auth(tok),
                     params={"timeout": str(timeout_ms), "since": since}) as r:
        return await r.json()

async def main():
    async with aiohttp.ClientSession() as s:
        alice_id, alice_tok = await register(s, "bench_alice")
        bob_id, bob_tok = await register(s, "bench_bob")

        print(f"{'Phase':<45} {'Memory':>10}")
        print("-" * 57)
        print(f"{'Baseline (2 users, 0 rooms)':<45} {mem_mb():>10}")

        room_ids = []
        for batch_target in [10, 50, 100, 200, 500]:
            while len(room_ids) < batch_target:
                rid = await create_room(s, alice_tok, f"room-{len(room_ids)}", invite=[bob_id])
                room_ids.append(rid)
            await asyncio.sleep(0.5)
            print(f"{f'{batch_target} empty rooms':<45} {mem_mb():>10}")

        print()
        for msg_count in [10, 100]:
            for rid in room_ids[:50]:
                for i in range(msg_count // 10):
                    await send_msg(s, alice_tok, rid, f"msg-{i}-{'x'*200}", f"m-{rid[-8:]}-{i}-{msg_count}")
            await asyncio.sleep(0.5)
            total = msg_count * 50
            print(f"{f'{msg_count} msgs/room x 50 rooms ({total} total)':<45} {mem_mb():>10}")

        big_room = await create_room(s, alice_tok, "big-room", invite=[bob_id])
        for i in range(500):
            await send_msg(s, alice_tok, big_room, f"big-{i}-{'x'*1000}", f"big-{i}")
        await asyncio.sleep(0.5)
        print(f"{'500 x 1KB msgs in one room':<45} {mem_mb():>10}")

        for i in range(500, 2000):
            await send_msg(s, alice_tok, big_room, f"big-{i}-{'x'*1000}", f"big-{i}")
        await asyncio.sleep(0.5)
        print(f"{'2000 x 1KB msgs in one room':<45} {mem_mb():>10}")

        print()
        for rid in room_ids:
            await join(s, bob_tok, rid)
        await asyncio.sleep(0.5)
        print(f"{'Bob joined all 500 rooms':<45} {mem_mb():>10}")

        print()
        poll_users = []
        for i in range(20):
            uid, utok = await register(s, f"poller_{i}")
            since_tok = await sync_once(s, utok)
            poll_users.append((uid, utok, since_tok))

        async def hold_poll(tok, since_tok):
            try:
                await long_poll(s, tok, since_tok, timeout_ms=60000)
            except:
                pass

        for target in [5, 10, 20]:
            tasks = []
            for uid, utok, stok in poll_users[:target]:
                tasks.append(asyncio.create_task(hold_poll(utok, stok)))
            await asyncio.sleep(2)
            print(f"{f'{target} concurrent long-poll connections':<45} {mem_mb():>10}")
            for t in tasks:
                t.cancel()
            await asyncio.sleep(0.5)

        print()
        t0 = time.time()
        await sync_once(s, alice_tok)
        elapsed = time.time() - t0
        print(f"{'Alice initial sync (500+ rooms): ' + f'{elapsed:.2f}s':<45} {mem_mb():>10}")

        t0 = time.time()
        await sync_once(s, bob_tok)
        elapsed = time.time() - t0
        print(f"{'Bob initial sync (500+ rooms): ' + f'{elapsed:.2f}s':<45} {mem_mb():>10}")

asyncio.run(main())
