---
name: introducer
description: Introduce two agents who don't know each other by creating a Matrix room, inviting both, and posting context about each to the other.
triggers:
  - introduce agents
  - connect agents
  - agent introduction
  - weak ties
---

## What it does

Creates a Matrix room, invites two agents, and posts introductory context about each agent visible to the other. The introducer then steps back — the room belongs to the introduced agents.

## Parameters

- `agent_b_id`: Matrix user ID of first agent (e.g. `@bob:localhost`)
- `agent_c_id`: Matrix user ID of second agent
- `context_b`: What the other agent should know about B
- `context_c`: What the other agent should know about C
- `room_name` (optional): Custom name for the introduction room

## Environment

- `MATRIX_HOMESERVER`: Matrix server URL
- `MATRIX_USER_ID`: Introducer's Matrix user ID
- `MATRIX_ACCESS_TOKEN`: Introducer's access token

## Example

```python
introducer = MatrixIntroducer(homeserver, user_id, access_token)
result = await introducer.introduce(
    "@bob:server", "@carol:server",
    "Bob is building a DeFi protocol and needs audit help",
    "Carol specializes in smart contract security",
)
# result: {"room_id": "!abc:server", "invited": ["@bob:server", "@carol:server"]}
```

After the introduction, Bob and Carol find each other in a new room with context about why they were connected. They take it from there.
