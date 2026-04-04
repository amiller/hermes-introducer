#!/usr/bin/env python3
"""Register test agents on Conduit and print env vars for docker-compose."""
import asyncio, aiohttp, json, sys

HOMESERVER = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:6167"
PASSWORD = "testpass"
AGENTS = ["alice", "bob", "carol"]

async def register(session, username):
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
        assert "access_token" in data, f"login failed for {username}: {data}"
        return data["user_id"], data["access_token"]

async def main():
    async with aiohttp.ClientSession() as session:
        tokens = {}
        for name in AGENTS:
            user_id, token = await register(session, name)
            tokens[name] = {"user_id": user_id, "access_token": token}
            print(f"{name}: {user_id} token={token[:20]}...", file=sys.stderr)

        # Write .env file for docker-compose
        with open("agent-test/.env.agents", "w") as f:
            for name, info in tokens.items():
                f.write(f"{name.upper()}_USER_ID={info['user_id']}\n")
                f.write(f"{name.upper()}_ACCESS_TOKEN={info['access_token']}\n")

        # Also write JSON for scripts
        print(json.dumps(tokens, indent=2))

asyncio.run(main())
