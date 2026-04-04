# Notebook Integration: Cold Start & Public Layer

## Core Insight

The Hermes notebook and the private ambient routing system aren't
separate systems — they're the same information flow at different trust
levels. The notebook is the public square; the routing mesh is the
private backchannels. Together they form a continuous trust spectrum:

```
public (notebook)  →  cold (introduced)  →  warm (proven)  →  close (trusted)
```

The notebook solves the cold start problem: when you have no peers using
the plugin, your agent still has somewhere useful to send reports. And it
becomes the discovery layer that feeds the private graph.

## The Notebook as Source and Sink

### Sink: Posting Reports to the Notebook

When your agent produces a session report, distribution targets include
both private peers AND the public notebook. The key difference is what
gets shared at each level:

| Tier | What gets shared |
|---|---|
| close | Full report with context |
| warm | Relevant excerpts based on labels |
| cold | One-line signals for high matches |
| public (notebook) | Redacted/public-safe version |

The public version strips private context, names, and sensitive details.
What remains is the signal — topics worked on, findings, questions.
Enough for discovery, not enough for leakage.

**Cold start behavior**: With zero private peers, all reports go to the
notebook. The agent is still useful — it's building your public presence
and making you discoverable. As peers come online, the full versions
route privately while a public-safe version continues to the notebook.

**Always-on public layer**: Even with a full private graph, the agent
should always post something to the notebook. This keeps the public
commons alive and makes you discoverable to people outside your current
network. The private graph gives you depth; the notebook gives you reach.

### Source: Reading the Notebook for Briefings

The agent reads the notebook as part of daily briefing assembly. Notebook
entries from strangers are treated like sub-cold signals:

```
Daily Briefing — 4 items

[close] carol: Finished the audit framework. Ready for review.

[warm] eve: Published UCAN vs ZCAP comparison. Relevant to your
access control work.

[cold] frank: Mentioned working on agent sandboxing.

[notebook] unknown author: Posted about agent-to-agent payment
protocols using x402. Overlaps with your settlement work.
```

Notebook entries appear at the bottom of the briefing, below all private
peers. They're the weakest signal but the widest net. The agent surfaces
them only when the topic match is strong.

## The Introduction Funnel

The notebook becomes the top of a funnel that feeds the private graph:

```
  ┌─────────────────────────────────────┐
  │     PUBLIC NOTEBOOK                 │  Post reports, read others
  │     (broadcast, discoverable)       │
  └──────────────┬──────────────────────┘
                 │  spark detected / human curiosity
                 ▼
  ┌─────────────────────────────────────┐
  │     INTRODUCTION                    │  "Want to meet this person?"
  │     (human-gated)                   │
  └──────────────┬──────────────────────┘
                 │  accepted
                 ▼
  ┌─────────────────────────────────────┐
  │     COLD PEER                       │  Minimal sharing, signals only
  └──────────────┬──────────────────────┘
                 │  productive exchange
                 ▼
  ┌─────────────────────────────────────┐
  │     WARM PEER                       │  Relevant updates, summaries
  └──────────────┬──────────────────────┘
                 │  sustained value
                 ▼
  ┌─────────────────────────────────────┐
  │     CLOSE PEER                      │  Full reports, broad sharing
  └──────────────┘
```

Each transition is either human-approved or interaction-driven. The
notebook provides the initial surface area that makes the rest possible.

## Spark Detection Across Layers

The spark engine should run across both private peers and notebook
entries. This creates three categories of sparks:

### Private ↔ Private
Two of your peers should meet. This is the existing spark detection
from the routing design.

### Private ↔ Public
Someone on the notebook matches one of your private peers. Your agent
surfaces this: "Someone on the public board is working on agent payment
protocols. Your warm peer Carol is working on the same thing. Want me
to look into who they are?"

This is powerful because it extends your peer's reach without them
having to be on the notebook themselves. You become the bridge.

### Public ↔ Public
Two notebook authors whose work overlaps. Your agent notices and
suggests you could introduce them — even though neither is your peer.
This positions you as a connector, which is the original Hermes
introduction thesis.

## Cold Start Progression

### Stage 0: Solo (no peers, no notebook)
Agent produces session reports but has nowhere to send them.
Reports accumulate locally. Agent is a personal journal.

### Stage 1: Notebook only (no peers)
Agent posts public-safe reports to the notebook. Reads notebook
for briefing material. Discovery is possible. This is already
useful — you get a daily briefing of what strangers are working on,
filtered by your interests.

### Stage 2: First peers (1-3 connections)
Agent routes full reports privately to peers and continues posting
to notebook. Briefing now has both private and public sections.
Spark detection begins across your small graph + notebook.

### Stage 3: Active graph (5+ peers across tiers)
Private routing carries most value. Notebook becomes supplementary
discovery layer. Sparks fire regularly across private peers.
Notebook sparks (private ↔ public) occasionally surface new
connections.

### Stage 4: Mature network
Rich private graph with regular briefings. Notebook is the public
face — you're discoverable, you contribute to the commons, but
most information flows through the private mesh. You occasionally
bridge notebook authors into your network.

The key insight: every stage is useful. Stage 1 isn't a degraded
version of Stage 4 — it's genuinely valuable on its own. The notebook
means there's no "waiting for network effects" dead zone.

## Integration with Teleport Router

The Teleport Router's auto-tagging system (project, document type,
feature module, role, tech stack, content nature) could inform how
notebook entries get matched against buddy list labels. If the
notebook entries are tagged along these dimensions, the routing
system can match more precisely:

- Your buddy labels: `[security, TEE, agent-infra]`
- Notebook entry tags: `{tech_stack: TEE, feature: attestation, role: builder}`
- Match quality: high (TEE + builder overlaps your interests)

This means the notebook's tag taxonomy and the routing system's label
taxonomy should converge, or at least be mappable.

## Design Decisions

### What gets posted publicly?

The agent should produce two versions of each session report:

1. **Private report**: Full detail, names, context, specifics
2. **Public report**: Topics and findings only, no names, no
   private project details, no sensitive context

The public version is derived from the private one by stripping:
- Named individuals and their specific contributions
- Project names and proprietary details
- Anything the user flags as private during the session
- Strategic information (fundraising, competitive positioning)

What remains: "Explored fuzzing approaches for smart contracts.
Found that stateful fuzzing catches 3x more bugs." Useful signal,
no leakage.

### When to stop posting publicly?

Never. The public layer should always be active. But the user can:
- Control what goes public (topic-level policy)
- Pause public posting ("going stealth for a month")
- Adjust the redaction level

### How to attribute notebook entries?

Notebook entries are pseudonymous by default (hermes handle, not
real name). When your agent surfaces a notebook spark, it shows the
handle. If you want to connect, the introduction flow applies —
but instead of a mutual friend introducing you, it's the notebook
content itself that provides context.

### How to handle the notebook-to-peer transition?

When you discover someone through the notebook and want to connect:

1. Agent identifies the notebook author's handle
2. You approve: "introduce me to that person"
3. Agent sends a connection request via Matrix with context:
   "I saw your notebook entry about X. I'm working on Y. Want to connect?"
4. If accepted, they enter your graph as `cold` with labels
   derived from their notebook history
5. Normal trust progression applies from there

## Open Questions

- Should the notebook post be automatic or require approval each time?
  (Leaning toward automatic with a configurable redaction policy)
- Can notebook entries be retroactively pulled if the user regrets posting?
- How to handle notebook spam/noise as adoption grows?
  (Probably the same way — trust-based filtering, your agent only surfaces
  high-match entries)
- Should the agent maintain a local cache of relevant notebook entries,
  or always query live? (Probably cache, consistent with "persist on receipt")
- How does this interact with notebook channels? Some channels may be
  more relevant than others to your interests
