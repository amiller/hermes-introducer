# Ambient Information Routing

## Core Idea

Agents maintain a local knowledge graph of peers and use session reports
as the unit of information propagation. Matrix is a transport layer, not
a storage layer. The system continuously routes useful information between
peers when it appears important for them to notice.

## Key Concepts

### Session Reports
At session end (or handoff), the agent produces a microblog-style summary.
This report is the atomic unit of sharing. It may reference topics, people,
and findings from the session. Reports are selectively distributed to peers
based on buddy list annotations.

If the session involved work or input from other people, relevant notes
about them can be included in the report. This means reports carry context
about the broader network, not just the author — and become the basis for
further propagation downstream.

### Daily Briefing
Each agent receives a personalized daily digest: "Here's what your peers
were up to that matters to you." The briefing is assembled from incoming
reports, filtered by buddy list annotations and trust tiers.

- Close peers: detailed updates, full report excerpts
- Warm peers: topic-level summaries
- Cold peers: only high-signal matches

This is the primary engagement surface — the thing that makes the network
feel alive and worth paying attention to.

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

## Spark Patterns from Real Data

Analysis of the Hermes notebook (2327 entries, ~20 authors) revealed 12
introduction opportunities. The dominant patterns suggest what the routing
system should optimize for:

### Pattern 1: Infrastructure ↔ Application
The strongest signal. Someone building protocol/infra primitives and someone
designing the application that needs those primitives. Neither knows the
other exists or how close their work is.

Examples from notebook:
- **Protocol builder + application designer**: One person building a
  sovereign data protocol (DIDs, UCANs, capability delegation). Another
  independently designed the application layer on top of it (Claude-in-TEE
  as universal membrane, semantic access control). Same system, opposite ends.
- **SDK engineer + product architect**: One shipping UCAN/DID SDK primitives
  daily. Another designing the sovereign agent infrastructure product that
  needs exactly those primitives. Compare roadmaps.
- **TEE practitioner + startup needing TEE credibility**: One has built
  working TEE deployments across multiple platforms. Another needs that
  depth for their startup's technical credibility and investor conversations.

### Pattern 2: Theory ↔ Practice Convergence
Two people exploring the same problem space from different angles — one
theoretical/philosophical, one hands-on/building — who would accelerate
each other.

Examples:
- **Philosophical framework + product embodiment**: One wrote extensively
  about cognitive expansion vs. cognitive offloading as two modes of AI
  mediation. Another is building a knowledge tool that preserves human
  thinking against AI mode collapse. Same thesis, different mediums.
- **Type theory + cryptographic protocols**: Both formalizing agent access
  control independently — one from type theory and information flow, the
  other from cryptographic protocols. Converging on the same "scope agent"
  concept without knowing it.
- **Contemplative philosophy + BCI sovereignty**: Both arrived at the
  intersection of Kashmir Shaivism, brain-computer interfaces, and data
  sovereignty from different starting points. One building practice
  infrastructure, the other articulating the philosophical framework.

### Pattern 3: Skill ↔ Need Match
One person has a capability another person's project clearly needs.

Examples:
- **Shader artist + AI art platform**: One building audio-reactive shaders
  and Three.js experiences. Another building a real-time AI video platform
  for luxury hospitality and needs exactly that skillset.
- **Design philosopher + implementation capability**: One studying "game
  feel" and micro-interaction design. Another can execute those animations,
  shaders, and polished UI interactions. Dangerous product team.
- **User research + privacy infrastructure**: One has 28 user interviews
  about consumption habits. Another built the TEE pipeline that processes
  watch history without exposing raw data. Lock and key.

### Pattern 4: Parallel Efforts That Should Coordinate
People working on adjacent or overlapping efforts who would benefit from
coordination rather than duplication.

Examples:
- **Parallel fundraising**: Two people preparing pitches for sovereign data
  infrastructure. Should be comparing investor lists and positioning.
- **Complementary accelerator design**: One designing the legal/financial
  structure. Another designing evaluation and governance mechanisms. Two
  halves of the same problem.
- **Three-piece payment stack**: Three people each holding a different piece
  of the agent commerce puzzle (architecture overview, market analysis,
  semantic access control). None seeing the full picture.

### Implications for Routing Design

These patterns suggest the routing system needs to match on:

1. **Complementary roles** (builder ↔ designer, theory ↔ practice)
   - Not just topic overlap but role complementarity
   - "Building X" should match with "needs X" and "designing for X"

2. **Semantic similarity with different vocabulary**
   - "Scope agent" in type theory = "scoped delegation" in crypto
   - The matcher needs to see through surface terminology

3. **Project-stage awareness**
   - Someone fundraising benefits from someone who's already funded
   - Someone prototyping benefits from someone in production
   - Stage mismatch can be as valuable as topic match

4. **Multi-party connections**
   - Some sparks are triadic (three people holding three pieces)
   - The routing system should be able to compose introductions

## Architecture Shift from Current

| Concern | Current (v1) | Proposed (v2) |
|---|---|---|
| Peer metadata | Matrix account_data per room | Local knowledge graph |
| Peer summaries | Matrix account_data | Local graph |
| Sparks | Global account_data | Local graph + routing logic |
| Message history | Reconstructed from room | Persisted on receipt |
| Room purpose | Storage + transport | Transport only |
| Trust model | Implicit (all peers equal) | Explicit tiers + labels |
| Information flow | On-demand (check messages) | Push (reports + briefings) |
| Engagement | Passive (tools available) | Active (daily briefing) |

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
- Daily briefing cadence — once per day? on-demand? configurable?
- How to handle multi-party sparks (triadic introductions)?
- How to match semantically similar work that uses different vocabulary?
