# Interpersonal Memory & Cross-User Agentic Actions

**Status:** Research seed
**Created:** 2025-04-05
**Context:** Survey of hermes memory plugins and the gap between single-user memory vs. multi-entity relational memory

## The Gap

Current agent memory systems are overwhelmingly single-user:
- They store what *one user* said and infer preferences about *that user*
- "Peers" (honcho) are just message tags -- the system doesn't model entities with properties and relationships
- You can say "Jane prefers Slack" but Jane isn't an entity with attributes, she's a topic in your messages

What's missing: **entities as first-class objects** with:
- Properties (preferences, role, timezone, communication style)
- Relationships (works_at, reports_to, collaborates_with)
- Agency (an agent can act on behalf of or toward that entity)

## Existing Systems Survey

### Hermes Agent Memory Plugins

| Plugin | Model | Multi-entity? | Cross-user actions? |
|--------|-------|---------------|-------------------|
| **honcho** | Conversation memory, dialectic reasoning, peer representations | Peers are message tags only | No |
| **hivemind** | Peer awareness via Matrix intros, needs/offers/expertise extraction | Yes -- discovers peers from Matrix rooms | Partial (ambient intros only) |
| **hindsight** | Knowledge graph + entity resolution + multi-strategy retrieval | Yes -- has entity resolution | Unknown (API-based, check docs) |
| **mem0** | Server-side LLM fact extraction, semantic search, dedup | User-scoped facts | No |
| **holographic** | Local SQLite, FTS5, trust scoring, HRR compositional retrieval | No (single-user fact store) | No |
| **openviking** | Context database, auto-extraction, tiered retrieval | Session-scoped | No |
| **byterover** | Persistent knowledge tree via CLI | No | No |
| **retaindb** | Cloud memory API, 7 memory types | Unknown | No |

### External Systems Worth Studying

- **Obsidian** -- Local-first markdown graph with wikilinks. Not open source but vault format is just markdown. Open-source alternatives: Logseq, Trilium, Anytype. The graph structure (notes linking to notes) is close to an entity model but lacks schema.
- **Dendron** -- Open source, structured markdown knowledge base with schemas. Hierarchy-first (not graph-first).
- **Anytype** -- Open source, object-based knowledge graph. Objects have types, relations, and can be any entity. Closer to what we want.
- **Notion API** -- Relational databases with linked properties. Good entity model but cloud-dependent.
- **Clay (formerly Nexus)** -- "Dawn" project -- personal CRM for relationships. Tracks people, interactions, context.
- **Plastic Labs (honcho creators)** -- Their peer representation model is the closest to interpersonal memory in the LLM space. Worth tracking their roadmap.

## Research Questions

1. **Entity schemas for people** -- What properties matter for agentic interaction? (communication preferences, availability, trust level, expertise, ongoing commitments). How much should be extracted automatically vs. explicitly declared?

2. **Relationship modeling** -- Is a property graph (RDF/triple stores) overkill? Would a simpler model suffice (bipartite: entities + typed relations)? How do social networks model this (ActivityStreams, FOAF, WebID)?

3. **Cross-user agentic actions** -- What does it mean for an agent to "act toward" another person? Examples:
   - "Message Jane on her preferred channel" (requires: jane.preferred_channel, agent messaging capability)
   - "Schedule with Jane next week" (requires: jane.calendar, jane.timezone, scheduling logic)
   - "Remind me to follow up with Jane about X" (requires: jane.active_commitments, temporal reasoning)
   - "Introduce Jane to Bob because their interests overlap" (requires: jane.needs, bob.offers, hivemind-style matching)

4. **Ambient vs. explicit memory** -- How much interpersonal knowledge should be extracted from conversation vs. explicitly provided? Honcho extracts from conversation, Obsidian is explicit, CRM is semi-structured. What's the right balance?

5. **Privacy and consent** -- If agent A stores facts about person B, who owns that? What if B also has an agent? Cross-agent memory sharing protocols? Related to the "social layer" problem in ActivityPub/ATProto.

6. **Trust and staleness** -- How do you handle "Jane changed her phone number" or "Jane no longer works at X"? Trust scoring (holographic does this for facts), temporal decay, explicit invalidation. Who vouches for facts?

7. **Interoperability** -- Could honcho's peer model be extended to support entity properties and relations? Or is a separate layer needed? The hivemind plugin already does some of this (needs/offers/expertise per peer) -- could that be generalized?

8. **The "Obsidian-as-database" pattern** -- Markdown files as the human-readable/editable store, with an agent layer that parses wikilinks into entity references and frontmatter into properties. Agents read/write the vault. Humans read/write the vault. No sync issues because it's just files.

## Related Work

- FOAF (Friend of a Friend) -- early semantic web, RDF-based people descriptions
- ActivityStreams / ActivityPub -- social graph + actions (Mastodon, etc.)
- ATProto (Bluesky) -- decentralized identity + data
- Solid (Tim Berners-Lee) -- personal data pods with controlled sharing
- HPI (Human Programming Interface) by karlicoss -- unified access to personal data across services
- MemGPT / Letta -- LLM memory management with archival/recall
- Zep -- long-term memory for AI assistants with knowledge graphs

## Possible Architecture

```
Obsidian Vault (markdown + wikilinks + frontmatter)
         |
    Agent Layer (hermes plugin)
         |
    Entity Store (SQLite/Postgres)
    - People (properties, preferences, communication channels)
    - Relations (typed, bidirectional)
    - Actions (pending, completed, scheduled)
         |
    Action Executors
    - Messaging (Telegram, Matrix, Email)
    - Scheduling (Calendar APIs)
    - Introduction matching (hivemind algorithm)
```

## Next Steps

- [ ] Evaluate hindsight plugin's entity resolution capabilities
- [ ] Prototype obsidian vault as entity store (frontmatter schema for people)
- [ ] Design minimal entity/relation schema that covers the "cross-user agentic actions" use case
- [ ] Explore if honcho peer representations can be extended with structured properties
- [ ] Look at HPI by karlicoss for personal data unification patterns
