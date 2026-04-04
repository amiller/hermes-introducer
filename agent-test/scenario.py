#!/usr/bin/env python3
"""
Full scenario: hermes-of-alice introduces hermes-of-bob and hermes-of-carol.

Bob is building a DeFi lending protocol and needs a security audit.
Carol is a TEE security researcher who does smart contract audits.
Alice knows both and tells hermes-of-alice to connect their agents.
"""
import asyncio, aiohttp, json, os, sys, uuid

HOMESERVER = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:6167"
PASSWORD = "testpass"
TOKEN = sys.argv[2] if len(sys.argv) > 2 else "agent-dev"
AGENTS = {
    "hermes-of-alice": "ALICE",
    "hermes-of-bob": "BOB",
    "hermes-of-carol": "CAROL",
}

async def register(session, username):
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

async def main():
    async with aiohttp.ClientSession() as session:
        print("=== Registering agents ===")
        creds = {}
        for agent_name, env_prefix in AGENTS.items():
            user_id, token = await register(session, agent_name)
            creds[agent_name] = (user_id, token, env_prefix)
            print(f"  {agent_name}: {user_id}")

        with open("agent-test/.env.agents", "w") as f:
            for agent_name, (user_id, token, env_prefix) in creds.items():
                f.write(f"{env_prefix}_USER_ID={user_id}\n")
                f.write(f"{env_prefix}_ACCESS_TOKEN={token}\n")
            zai_key = os.environ.get("ZAI_API_KEY", "")
            if zai_key:
                f.write(f"ZAI_API_KEY={zai_key}\n")

        alice_id, alice_tok, _ = creds["hermes-of-alice"]
        bob_id, _, _ = creds["hermes-of-bob"]
        carol_id, _, _ = creds["hermes-of-carol"]

        print("\n=== hermes-of-alice creates introduction ===")
        headers = {"Authorization": f"Bearer {alice_tok}"}
        async with session.post(f"{HOMESERVER}/_matrix/client/v3/createRoom",
            headers=headers,
            json={
                "name": "hermes-of-bob meets hermes-of-carol — DeFi security audit",
                "invite": [bob_id, carol_id],
                "preset": "private_chat",
            }
        ) as resp:
            room = await resp.json()
            room_id = room["room_id"]
            print(f"  Room: {room_id}")

        messages = [
            f"About {bob_id}: This is hermes-of-bob, the agent for Bob. "
            f"Bob is building a DeFi lending protocol called 'Meridian Finance' on Ethereum L2. "
            f"The protocol handles ~$2M TVL in testnet and is preparing for mainnet launch. "
            f"Bob needs a comprehensive security audit before going live — specifically around the liquidation engine "
            f"and the oracle integration with Chainlink. Bob's team is 3 developers, all strong in Rust and Solidity.",

            f"About {carol_id}: This is hermes-of-carol, the agent for Carol. "
            f"Carol is an independent security researcher who specializes in TEE attestation "
            f"and smart contract auditing. She's completed 12 audits in the past year including two major DeFi protocols. "
            f"Carol has deep expertise in reentrancy attacks, flash loan vectors, and oracle manipulation. "
            f"She recently published a paper on formal verification of lending pool invariants.",

            f"Why I'm connecting you: Bob's Meridian Finance protocol needs exactly the kind of audit Carol specializes in. "
            f"The liquidation engine and oracle integration are the highest-risk components. "
            f"Carol's recent work on lending pool formal verification is directly relevant. "
            f"I think you two should discuss scope, timeline, and whether Carol's availability works for Bob's mainnet target.",
        ]

        for msg in messages:
            txn = uuid.uuid4().hex
            async with session.put(
                f"{HOMESERVER}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
                headers=headers,
                json={"msgtype": "m.text", "body": msg},
            ) as resp:
                assert (await resp.json()).get("event_id"), "send failed"

        print(f"  Posted 3 introduction messages")
        print(f"\n=== Scenario ready ===")
        print(f"Room: {room_id}")
        print(f"hermes-of-bob and hermes-of-carol have pending invites.")

asyncio.run(main())
