import sys, os, types
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

# Stub agent.memory_provider so hivemind can import outside hermes-agent
if "agent" not in sys.modules:
    agent_mod = types.ModuleType("agent")
    mp_mod = types.ModuleType("agent.memory_provider")
    class MemoryProvider:
        def is_available(self): return False
        def initialize(self, session_id, **kw): pass
        def system_prompt_block(self): return ""
        def prefetch(self, query, **kw): return ""
        def get_tool_schemas(self): return []
        def handle_tool_call(self, name, args, **kw): return "{}"
        def shutdown(self): pass
    mp_mod.MemoryProvider = MemoryProvider
    agent_mod.memory_provider = mp_mod
    sys.modules["agent"] = agent_mod
    sys.modules["agent.memory_provider"] = mp_mod

HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:6167")
PASSWORD = "testpass"
TOKEN = os.environ.get("MATRIX_REGISTRATION_TOKEN", "agent-dev")

async def register_user(session, username):
    """Register on Continuwuity (two-step UIAA) or login if exists."""
    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
    }) as resp:
        data = await resp.json()
        if "access_token" in data:
            return data["user_id"], data["access_token"]
        uiaa_session = data.get("session", "")

    async with session.post(f"{HOMESERVER}/_matrix/client/v3/register", json={
        "username": username, "password": PASSWORD,
        "auth": {"type": "m.login.registration_token", "token": TOKEN, "session": uiaa_session},
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
