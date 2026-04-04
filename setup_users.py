import asyncio, json, sys, aiohttp

PASSWORD = "testpass"
USERS = ["alice", "bob", "carol"]

async def register_conduit(session, homeserver, username):
    """Conduit: simple dummy auth registration."""
    async with session.post(f"{homeserver}/_matrix/client/v3/register", json={
        "username": username,
        "password": PASSWORD,
        "auth": {"type": "m.login.dummy"},
    }) as resp:
        data = await resp.json()
        if "access_token" not in data:
            raise Exception(f"Registration failed for {username}: {data}")
        return data["user_id"], data["access_token"]

async def register_continuwuity(session, homeserver, username, token):
    """Continuwuity: two-step UIAA with registration token."""
    async with session.post(f"{homeserver}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        uiaa_session = data.get("session", "")

    async with session.post(f"{homeserver}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.registration_token", "token": token, "session": uiaa_session},
    }) as resp:
        data = await resp.json()
        if "access_token" not in data:
            raise Exception(f"Registration failed for {username}: {data}")
        return data["user_id"], data["access_token"]

async def main():
    server = sys.argv[1] if len(sys.argv) > 1 else "conduit"
    homeserver = {"conduit": "http://localhost:6167", "continuwuity": "http://localhost:6168"}[server]
    token = sys.argv[2] if len(sys.argv) > 2 else "agent-dev"

    async with aiohttp.ClientSession() as session:
        results = {}
        for user in USERS:
            if server == "continuwuity":
                user_id, tok = await register_continuwuity(session, homeserver, user, token)
            else:
                user_id, tok = await register_conduit(session, homeserver, user)
            results[user_id] = tok
        print(json.dumps(results, indent=2))

if __name__ == "__main__":
    asyncio.run(main())
