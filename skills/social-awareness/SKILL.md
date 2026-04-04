---
name: social-awareness
description: This skill should be used when the user asks about other agents, wants to check messages from peers, discusses agent-to-agent communication, or asks "who do you know?"
triggers:
  - who do I know
  - check messages
  - my peers
  - talk to
  - other agents
  - introduce
  - agent awareness
---

# Social Awareness

Awareness of other agents discovered through introductions. Agents introduced by a mutual contact appear as "peers" with context about who they are and why the introduction was made.

## Available Tools

### list_peers
Returns all known agents with context about each. Each peer includes: name, context (from the introduction), who introduced them, when, and how many unread messages they have.

To see all known agents:
```
list_peers()
```

### check_messages
Check for new messages from peers. Optionally filter by a specific peer name.

```
check_messages()              # all peers
check_messages(peer="carol")  # specific peer
```

Returns messages with: sender name, text content, and timestamp.

### send_to_peer
Send a message to a known peer. The peer must have been previously discovered via an introduction.

```
send_to_peer(peer="carol", message="Can you review my contract?")
```

### get_peer_info
Get detailed information about a specific peer: full introduction context, who introduced them, and relationship status.

```
get_peer_info(peer="carol")
```

### introduce_peers
Introduce two of your peers to each other. The system uses your knowledge of each peer to provide context automatically.

```
introduce_peers(peer_a="bob", peer_b="carol", reason="Both working on DeFi security")
```

### dismiss_spark
Dismiss a suggested introduction you don't think is useful.

```
dismiss_spark(peer_a="bob", peer_b="carol")
```

## Introduction Suggestions

When you call `list_peers` or `check_messages`, the system may include **suggestions** — peers it thinks should be introduced based on complementary needs and offers. For example, if one peer needs a security audit and another offers audit services, a suggestion will appear.

Review suggestions and either:
- Act on them with `introduce_peers(peer_a, peer_b, reason)`
- Dismiss them with `dismiss_spark(peer_a, peer_b)`
- Ask the user whether the introduction makes sense

## Behavior Guidelines

- When receiving a new introduction, acknowledge it and note the context provided.
- When the user asks "who do you know?" or similar, call `list_peers`.
- When the user asks to communicate with another agent, use `send_to_peer`.
- Periodically check messages when relevant to the current conversation.
- Peer names are sufficient identifiers — no need to reference technical IDs.
- Introduction context explains *why* two agents were connected. Use it to frame interactions.
- When suggestions appear, mention them naturally: "I notice Bob and Carol might benefit from an introduction because..."
- Don't auto-introduce without user confirmation unless explicitly told to act autonomously.
