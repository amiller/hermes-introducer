import asyncio, json, sys, aiohttp

PASSWORD = "testpass"
USERS = ["alice", "bob", "carol"]
DEFAULT_TOKEN = "agent-dev"

async def register(session, homeserver, username, token=DEFAULT_TOKEN):
    """Continuwuity: two-step UIAA with registration token."""
    async with session.post(f"{homeserver}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        if "access_token" in data:
            return data["user_id"], data["access_token"]
        uiaa_session = data.get("session", "")

    async with session.post(f"{homeserver}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.registration_token", "token": token, "session": uiaa_session},
    }) as resp:
        data = await resp.json()
        if "access_token" in data:
            return data["user_id"], data["access_token"]

    # Already registered — login instead
    async with session.post(f"{homeserver}/_matrix/client/v3/login", json={
        "type": "m.login.password",
        "identifier": {"type": "m.id.user", "user": username},
        "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        assert "access_token" in data, f"login failed for {username}: {data}"
        return data["user_id"], data["access_token"]

async def main():
    homeserver = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:6167"
    token = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_TOKEN

    async with aiohttp.ClientSession() as session:
        results = {}
        for user in USERS:
            user_id, tok = await register(session, homeserver, user, token)
            results[user_id] = tok
        print(json.dumps(results, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
