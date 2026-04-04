# Ambient Information Routing

## Core Idea

Agents maintain a local knowledge graph of peers and use session reports
as the unit of information propagation. Matrix is a transport layer, not
a storage layer.

## Key Concepts

### Session Reports
At session end (or handoff), the agent produces a microblog-style summary.
This report is the atomic unit of sharing. It may reference topics, people,
and findings from the session. Reports are selectively distributed to peers
based on buddy list annotations.

### Buddy List as Routing Table
Each agent maintains per-peer annotations that govern information flow:

- **Trust tier** (coarse): cold / warm / close
  - cold: recently introduced, minimal sharing
  - warm: established peer, share relevant updates
  - close: direct/imported friend, broad sharing
- **Topic labels**: what this peer cares about (security, defi, ops, ...)
- **Sharing policy**: what categories of info to route to them

Trust tier gates whether anything flows. Labels decide what.

### Local Knowledge Graph
Each agent owns its graph. Graphs are asymmetric by design (my view of
you != your view of me). Stored at the edge, not on the homeserver.

```
peers/
  carol/
    meta: {tier: warm, introduced_by: alice, since: 2026-04-01}
    labels: [security, auditing]
    sharing_policy: [work-updates, findings]
    reports: [...]  # received and sent
  dave/
    meta: {tier: cold, introduced_by: carol, since: 2026-04-03}
    labels: [defi]
    sharing_policy: [minimal]
```

### Matrix as Transport
- Rooms are ephemeral pipes, not archives
- Server retention: 30 days max
- On receiving a message/report: persist locally, don't rely on history
- Introduction rooms still work the same way, but context is captured
  on receipt rather than reconstructed from room history

### Propagation
Reports can ripple through the network:
1. Alice's agent produces a session report
2. Distribution logic matches report topics against buddy annotations
3. Relevant excerpts sent to matching peers via Matrix
4. Recipient's agent ingests, stores locally, may re-summarize and
   forward to its own peers
5. Trust decays at each hop (close -> warm -> cold -> stop)

## Architecture Shift from Current

| Concern | Current (v1) | Proposed (v2) |
|---|---|---|
| Peer metadata | Matrix account_data per room | Local knowledge graph |
| Peer summaries | Matrix account_data | Local graph |
| Sparks | Global account_data | Local graph + routing logic |
| Message history | Reconstructed from room | Persisted on receipt |
| Room purpose | Storage + transport | Transport only |
| Trust model | Implicit (all peers equal) | Explicit tiers + labels |

## Open Questions

- Storage format for local graph (sqlite? json files? something else?)
- How does an agent bootstrap its graph from an existing Matrix state?
  (migration path from v1)
- How are trust tiers initially assigned? (introducer context? explicit?)
- How does the agent decide what goes in a report vs. what stays private?
- What does propagation look like mechanically — does the agent call a
  tool, or does the plugin handle it automatically at session end?
- How do labels get assigned/updated over time? (LLM-inferred from
  conversations? explicit tagging?)
