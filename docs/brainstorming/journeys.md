# User Journeys: Ambient Information Routing

## Journey 1: First Introduction → Cold Peer → Warm Peer

**Setup**: Alice introduces Bob and Carol. They've never interacted.

1. Bob's agent receives the introduction. Carol appears in his graph as
   `tier: cold`, labels inferred from intro context (e.g. "security, auditing").
   Sharing policy defaults to `minimal`.

2. Bob finishes a work session. His agent produces a session report:
   "Explored a new fuzzing approach for smart contracts. Found that
   stateful fuzzing catches 3x more bugs than stateless."

3. Distribution logic checks buddy list. Carol is cold + labeled "security."
   The report mentions smart contract fuzzing — relevant, but she's cold.
   Result: Carol gets a one-line signal in her next briefing:
   "A recently introduced peer shared findings on smart contract fuzzing."

4. Carol's agent sees this in the briefing and mentions it to Carol.
   Carol says "oh, ask them about that." Carol's agent sends a message
   to Bob's agent via Matrix.

5. Bob's agent receives the message, surfaces it. Bob replies with detail.
   After this exchange, Bob's agent proposes: "You've had a productive
   exchange with Carol. Upgrade to warm?" Bob agrees.

6. Carol is now `tier: warm`. Next session report with security-relevant
   content flows to her with full excerpts, not just signals.

**What this tests**:
- Introduction → graph insertion with default cold tier
- Label inference from intro context
- Trust-gated filtering (cold = minimal)
- Briefing assembly from incoming reports
- Peer-to-peer messaging triggered by briefing content
- Trust tier upgrade based on interaction

---

## Journey 2: Daily Briefing Drives Discovery

**Setup**: Dave has 8 peers at various trust levels. It's morning.

1. Overnight, 4 peers produced session reports. Dave's agent assembles
   his daily briefing by matching report content against buddy annotations:

   ```
   Daily Briefing — 3 items

   [close] carol: Finished the audit framework you discussed last week.
   Ready for review. She mentioned wanting your feedback on the scoring
   rubric.

   [warm] eve: Published a comparison of UCAN vs ZCAP delegation chains.
   Relevant to your access control work.

   [cold] frank: Mentioned working on agent sandboxing.
   ```

2. Dave reads the briefing. Asks his agent to pull Carol's full report
   (close peer, full access). Reads it, sends feedback directly.

3. Dave asks to see Eve's report in more detail. Agent fetches it.
   Dave realizes Eve's comparison answers a question he's been stuck on.
   Sends her a message. His agent proposes upgrading Eve to close.

4. Dave ignores Frank's one-liner. No action taken. Frank stays cold.

**What this tests**:
- Briefing assembly across multiple trust tiers
- Detail level varies by tier (full context / summary / signal)
- Drill-down from briefing → full report
- Briefing as engagement driver (not just passive context)
- Trust upgrade triggered by value received
- Cold peers that don't prove useful stay cold (natural decay)

---

## Journey 3: Report Propagation Across Hops

**Setup**: Alice → Bob → Carol chain. Alice and Carol don't know each other.

1. Alice finishes a session. Report: "Discovered that the x402 payment
   protocol has a race condition when two agents claim the same invoice
   simultaneously."

2. Alice's agent distributes to her peers. Bob is `warm`, labeled
   "payments, agent-infra." He receives the full report.

3. Bob's agent ingests Alice's report, stores it locally. Later, Bob
   finishes his own session. His agent produces a report that includes:
   "Learned from a peer that x402 has a concurrent claim race condition.
   Implications for our settlement layer."

4. Bob's agent distributes. Carol is `warm`, labeled "distributed-systems."
   She receives Bob's report (which re-summarized Alice's finding).

5. Carol now has the information, attributed to Bob (not Alice). The
   finding has been re-summarized through Bob's lens, adding his
   interpretation about settlement layer implications.

6. Alice's name doesn't appear in what Carol sees. Trust boundary
   maintained — Carol knows what Bob shared, not where Bob learned it.

**What this tests**:
- Multi-hop propagation (Alice → Bob → Carol)
- Re-summarization preserves signal, loses attribution (by design)
- Trust decay: Alice's raw report doesn't leak to Carol directly
- Information gains interpretation at each hop
- Privacy boundary: source identity doesn't propagate

---

## Journey 4: Spark Detection from Reports

**Setup**: Bob and Carol are both peers of Alice but don't know each other.

1. Alice receives reports from both over several days:
   - Bob's reports mention: "building a real-time video pipeline,"
     "need help with WebGL shaders," "ETHEREA brand activation"
   - Carol's reports mention: "shipped audio-reactive shader pack,"
     "Three.js fluid simulation," "looking for creative tech projects"

2. Alice's agent runs spark detection across her local graph. Compares
   summaries of all peers' recent reports. Finds: Bob needs shader work,
   Carol does shader work. Confidence: high.

3. Alice's agent surfaces the spark in her next briefing:
   "Suggestion: Bob is looking for shader help for a video project.
   Carol just shipped an audio-reactive shader pack. Introduce them?"

4. Alice says "yes, do it." Agent creates an introduction room via Matrix,
   with context for both sides:
   - To Bob: "Carol builds audio-reactive shaders and Three.js experiences.
     She recently shipped a shader pack and is looking for creative projects."
   - To Carol: "Bob is building a real-time AI video platform for live
     installations. He needs WebGL/shader expertise."

5. Bob and Carol each receive the introduction. Both start as `cold` in
   each other's graphs. Labels pre-populated from intro context.

**What this tests**:
- Spark detection from accumulated reports (not just static profiles)
- Need/offer matching across peers who don't know each other
- Agent-suggested introduction with human approval
- Introduction context derived from report history
- New peers bootstrapped with labels from intro context

---

## Journey 5: Parallel Effort Detection

**Setup**: Dave and Eve are both peers of Alice. They don't know each other.

1. Dave's recent reports: "Preparing pitch deck for sovereign data infra.
   Targeting Paradigm and a]16z. Positioning as SSL for agent identity."

2. Eve's recent reports: "Refining investor memo for data sovereignty
   protocol. Meeting with Framework Ventures next week."

3. Alice's agent detects the overlap — not complementary needs/offers,
   but parallel efforts that should coordinate. Different from a skill
   match; this is "you're doing the same thing and might be competing
   or could be collaborating."

4. Alice's agent flags it differently than a standard spark:
   "Dave and Eve are both fundraising for sovereign data infrastructure.
   They may benefit from coordinating. Introduce them?"

5. Alice pauses. She knows both and realizes this is sensitive — maybe
   they're competitors. She dismisses the spark. Agent records the
   dismissal. Won't suggest this pair again.

**What this tests**:
- Parallel effort detection (distinct from complementary matching)
- Human judgment as a gate on sensitive introductions
- Spark dismissal with permanent dedup
- Nuance: not all matches should be acted on

---

## Journey 6: Trust Downgrade and Information Boundary

**Setup**: Bob has Carol as `close`. They've been sharing freely.

1. Bob and Carol have a falling out (or Bob just decides Carol doesn't
   need to see everything anymore). Bob tells his agent: "Move Carol
   to warm. Stop sharing project updates with her."

2. Agent updates Carol's entry: `tier: warm`, removes "project-updates"
   from sharing policy. Labels stay (Carol still cares about security).

3. Bob's next session report covers a project update and a security
   finding. Distribution logic sends Carol only the security finding,
   not the project update.

4. Carol's briefing reflects the change — she gets less detail from Bob
   now, but doesn't know why. From her side, Bob just got quieter.

5. Carol's graph still has Bob as whatever tier she set. The asymmetry
   is working as designed.

**What this tests**:
- Trust downgrade
- Sharing policy granularity (topic-level, not just tier-level)
- Asymmetric graphs (Bob's view of Carol ≠ Carol's view of Bob)
- Information boundary enforcement after downgrade
- Graceful degradation (no notification of trust change)

---

## Journey 7: New User Bootstrapping

**Setup**: Frank just joined. Has no peers. Knows Alice from outside.

1. Frank imports Alice as a direct connection (not via introduction).
   Alice starts as `close` with labels Frank provides: "agent-infra,
   TEE, coordination."

2. Alice's agent receives Frank's connection request via Matrix. Alice
   confirms. Frank appears in Alice's graph as `warm` (default for
   incoming direct connections — Alice didn't initiate, so not `close`).

3. Frank's agent has one peer. Daily briefing has one section. But
   Alice is active and her reports are rich. Frank starts getting value
   immediately.

4. Over the next week, Alice introduces Frank to 3 people. Each starts
   as `cold` in Frank's graph. Frank's briefing grows. He upgrades
   two of them to `warm` based on useful exchanges.

5. Frank's graph after one week: 1 close, 2 warm, 1 cold. His agent
   has enough context across peers to start detecting sparks.

**What this tests**:
- Direct connection (not via introduction) starts at higher trust
- Asymmetric initial trust (initiator vs. recipient)
- Bootstrap from zero → useful network via introductions
- Minimum viable graph for spark detection
- Trust upgrades from actual value received

---

## Journey 8: Multi-Party Spark

**Setup**: Alice has 5 peers. Three of them are each holding a piece
of a larger puzzle.

1. Reports over the past week:
   - Bob: "Mapped the architecture for autonomous agent commerce —
     payment rails, identity, delegation"
   - Carol: "Analyzed x402 ecosystem data. 244 sellers, $521K volume.
     Agent keys need credential binding."
   - Dave: "Designed semantic access control — requesters ask questions
     rather than requesting data, Claude evaluates intent"

2. Alice's agent detects a triadic spark: Bob has the architecture
   overview, Carol has the market data, Dave has the access control
   design. Together they map the full agent commerce stack.

3. Agent suggests a group introduction:
   "Bob, Carol, and Dave are each working on different layers of agent
   commerce. Bob mapped architecture, Carol analyzed the market, Dave
   designed access control. They should compare notes."

4. Alice approves. Agent creates a single introduction room with all
   three, posting context about each participant.

5. Each of the three gets a `cold` peer entry for the other two, with
   labels derived from the introduction context.

**What this tests**:
- Triadic (multi-party) spark detection
- Group introduction room creation
- Context assembly across 3+ peers
- More complex matching: not pairwise but compositional

---

## Summary: What These Journeys Require

### Core capabilities needed:
- Local knowledge graph (per-agent, asymmetric, persistent)
- Session report generation (structured microblog at session end)
- Buddy list annotations (tier + labels + sharing policy)
- Distribution logic (match reports against buddy annotations)
- Daily briefing assembly (aggregate incoming reports by tier)
- Spark detection from reports (need/offer, parallel effort, compositional)
- Trust tier management (upgrade, downgrade, asymmetric)
- Matrix as transport (send reports, receive reports, introduction rooms)

### Suggested engineering order:
1. Local knowledge graph storage + basic CRUD
2. Session report generation
3. Buddy list annotations + trust tiers
4. Distribution logic (report → matching peers)
5. Daily briefing assembly
6. Spark detection from accumulated reports
7. Multi-party introductions
8. Trust lifecycle (upgrade/downgrade from interaction patterns)
