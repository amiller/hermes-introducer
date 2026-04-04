"""Hive Mind memory plugin — peer awareness and ambient introductions via Matrix.

Implements the MemoryProvider ABC so that peer context and introduction
suggestions are injected into the agent's context on every turn via prefetch().

Config via environment variables:
  MATRIX_HOMESERVER    — Matrix server URL (e.g. http://conduit:6167)
  MATRIX_USER_ID       — Matrix user ID (@hermes-of-bob:localhost)
  MATRIX_ACCESS_TOKEN  — Matrix access token
"""

import asyncio, json, logging, os, queue, threading, uuid
from datetime import datetime, timezone
from typing import Any, Dict, List

from agent.memory_provider import MemoryProvider

logger = logging.getLogger(__name__)

# Lazy import — matrix_backend.py may be in plugin dir or on sys.path
_MatrixBackend = None

def _get_backend_class():
    global _MatrixBackend
    if _MatrixBackend is None:
        from matrix_backend import MatrixBackend
        _MatrixBackend = MatrixBackend
    return _MatrixBackend


_loop = None
_loop_thread = None

def _get_loop():
    global _loop, _loop_thread
    if _loop is None or _loop.is_closed():
        _loop = asyncio.new_event_loop()
        _loop_thread = threading.Thread(
            target=_loop.run_forever, daemon=True, name="hivemind-loop",
        )
        _loop_thread.start()
    return _loop

def _run_async(coro):
    loop = _get_loop()
    future = asyncio.run_coroutine_threadsafe(coro, loop)
    return future.result(timeout=30)


SUMMARY_KEY = "social.awareness.summary"
SPARKS_KEY = "social.awareness.sparks"
STALENESS_THRESHOLD = 5

SUMMARIZE_PROMPT = (
    "Analyze this peer based on their introduction context and messages. "
    "Return JSON with keys: needs (list[str]), offers (list[str]), "
    "expertise (list[str]), summary_text (str). "
    "Be specific and concise. 2-4 items per category."
)

SPARK_PROMPT = (
    "Evaluate whether two peers should be introduced. "
    "Return JSON with keys: should_introduce (bool), reason (str), confidence (str: high/medium/low). "
    "Only suggest introductions with clear mutual benefit."
)

SYSTEM_PROMPT = """## Hive Mind — Peer Awareness

You are aware of other agents through introductions. When someone introduces you to another agent, you automatically become aware of them as a "peer."

Your peer context is refreshed every turn — check the Peers section above for who you know and any introduction suggestions.

### Available Tools

- `hivemind_list_peers()` — list all known peers with context
- `hivemind_check_messages(peer="")` — check messages, optionally from a specific peer
- `hivemind_send_to_peer(peer, message)` — send a message to a peer
- `hivemind_get_peer_info(peer)` — detailed info about a peer
- `hivemind_introduce_peers(peer_a, peer_b, reason="")` — introduce two peers to each other
- `hivemind_dismiss_spark(peer_a, peer_b)` — dismiss a suggested introduction

### Guidelines

- When suggestions appear, mention them naturally and confirm with the user before acting.
- Peer names are sufficient identifiers — no need for technical IDs.
- Introduction context explains *why* two agents were connected. Use it to frame interactions."""


# -- Tool Schemas (OpenAI function calling format) --

LIST_PEERS = {
    "name": "hivemind_list_peers",
    "description": "List all agents you know, with context about each.",
    "parameters": {"type": "object", "properties": {}, "required": []},
}

CHECK_MESSAGES = {
    "name": "hivemind_check_messages",
    "description": "Check for messages from peers. Optionally filter by peer name.",
    "parameters": {
        "type": "object",
        "properties": {"peer": {"type": "string", "description": "Peer name to filter by (optional)"}},
        "required": [],
    },
}

SEND_TO_PEER = {
    "name": "hivemind_send_to_peer",
    "description": "Send a message to a known peer.",
    "parameters": {
        "type": "object",
        "properties": {
            "peer": {"type": "string", "description": "Peer name"},
            "message": {"type": "string", "description": "Message to send"},
        },
        "required": ["peer", "message"],
    },
}

GET_PEER_INFO = {
    "name": "hivemind_get_peer_info",
    "description": "Get detailed information about a specific peer.",
    "parameters": {
        "type": "object",
        "properties": {"peer": {"type": "string", "description": "Peer name"}},
        "required": ["peer"],
    },
}

INTRODUCE_PEERS = {
    "name": "hivemind_introduce_peers",
    "description": "Introduce two of your peers to each other by creating a shared context.",
    "parameters": {
        "type": "object",
        "properties": {
            "peer_a": {"type": "string", "description": "First peer name"},
            "peer_b": {"type": "string", "description": "Second peer name"},
            "reason": {"type": "string", "description": "Why they should meet"},
        },
        "required": ["peer_a", "peer_b"],
    },
}

DISMISS_SPARK = {
    "name": "hivemind_dismiss_spark",
    "description": "Dismiss a suggested introduction between two peers.",
    "parameters": {
        "type": "object",
        "properties": {
            "peer_a": {"type": "string", "description": "First peer name"},
            "peer_b": {"type": "string", "description": "Second peer name"},
        },
        "required": ["peer_a", "peer_b"],
    },
}

ALL_TOOLS = [LIST_PEERS, CHECK_MESSAGES, SEND_TO_PEER, GET_PEER_INFO, INTRODUCE_PEERS, DISMISS_SPARK]


# -- Spark Engine --

async def _summarize_peer(backend, peer_name, messages, context):
    from agent.auxiliary_client import call_llm
    msg_text = "\n".join(f"{m.get('sender','')}: {m.get('content',{}).get('body','')}"
                         for m in messages if m.get("type") == "m.room.message")
    resp = call_llm(
        task="hivemind",
        messages=[
            {"role": "system", "content": SUMMARIZE_PROMPT},
            {"role": "user", "content": f"Peer: {peer_name}\nContext: {context}\n\nMessages:\n{msg_text}"},
        ],
        max_tokens=300,
    )
    return json.loads(resp.choices[0].message.content)


async def _detect_sparks(summaries):
    from agent.auxiliary_client import call_llm
    sparks = []
    for i, a in enumerate(summaries):
        for b in summaries[i+1:]:
            prompt = (
                f"Peer A — {a['peer_name']}:\n"
                f"  Needs: {', '.join(a.get('needs', []))}\n"
                f"  Offers: {', '.join(a.get('offers', []))}\n\n"
                f"Peer B — {b['peer_name']}:\n"
                f"  Needs: {', '.join(b.get('needs', []))}\n"
                f"  Offers: {', '.join(b.get('offers', []))}\n"
            )
            resp = call_llm(
                task="hivemind",
                messages=[
                    {"role": "system", "content": SPARK_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                max_tokens=150,
            )
            ev = json.loads(resp.choices[0].message.content)
            if ev.get("should_introduce") and ev.get("confidence") in ("high", "medium"):
                sparks.append({
                    "peer_a": a["peer_name"], "peer_b": b["peer_name"],
                    "reason": ev.get("reason", ""), "confidence": ev["confidence"],
                })
    return sparks


async def _maybe_update_and_spark(backend, peers):
    updated_any = False
    all_summaries = []
    stale_count = 0

    for peer in peers[:10]:
        room_id = backend._resolve_peer(peer["name"])
        if not room_id:
            continue
        summary = await backend._get_account_data(room_id, SUMMARY_KEY)
        messages = await backend._get_messages(room_id, limit=30)
        msg_count = len([m for m in messages if m.get("type") == "m.room.message"])

        stale = (
            summary is None
            or abs(msg_count - summary.get("message_count_at_update", 0)) >= STALENESS_THRESHOLD
        )

        if stale and stale_count < 2:
            new_summary = await _summarize_peer(backend, peer["name"], messages, peer.get("context", ""))
            new_summary["peer_name"] = peer["name"]
            new_summary["last_updated"] = datetime.now(timezone.utc).isoformat()
            new_summary["message_count_at_update"] = msg_count
            await backend._put_account_data(room_id, SUMMARY_KEY, new_summary)
            summary = new_summary
            updated_any = True
            stale_count += 1

        if summary:
            all_summaries.append(summary)

    if updated_any and len(all_summaries) >= 2:
        new_sparks = await _detect_sparks(all_summaries)
        existing = await backend._get_global_account_data(SPARKS_KEY) or {"sparks": []}
        existing_pairs = {tuple(sorted([s["peer_a"], s["peer_b"]])) for s in existing["sparks"]}
        for spark in new_sparks:
            pair = tuple(sorted([spark["peer_a"], spark["peer_b"]]))
            if pair not in existing_pairs:
                spark["id"] = uuid.uuid4().hex[:8]
                spark["created_at"] = datetime.now(timezone.utc).isoformat()
                spark["status"] = "pending"
                existing["sparks"].append(spark)
                existing_pairs.add(pair)
        await backend._put_global_account_data(SPARKS_KEY, existing)

    sparks_data = await backend._get_global_account_data(SPARKS_KEY) or {"sparks": []}
    return [s for s in sparks_data["sparks"] if s["status"] == "pending"]


async def _update_spark_status(backend, peer_a, peer_b, status):
    pair = tuple(sorted([peer_a, peer_b]))
    data = await backend._get_global_account_data(SPARKS_KEY) or {"sparks": []}
    for s in data["sparks"]:
        if tuple(sorted([s["peer_a"], s["peer_b"]])) == pair:
            s["status"] = status
    await backend._put_global_account_data(SPARKS_KEY, data)


def _format_context(peers, suggestions):
    if not peers:
        return ""
    lines = ["## Peers", f"You know {len(peers)} agent(s):"]
    for p in peers:
        lines.append(f"- {p['name']} (introduced by {p['introduced_by']}): {p['context'][:120]}")
    if suggestions:
        lines.append("\n## Suggestions")
        for s in suggestions:
            lines.append(
                f"- {s['peer_a']} and {s['peer_b']} might benefit from an introduction: "
                f"{s['reason']} (confidence: {s['confidence']})"
            )
    return "\n".join(lines)


# -- Tool dispatch --

async def _dispatch(backend, tool_name, args):
    if tool_name == "hivemind_list_peers":
        return await backend.get_peers()

    if tool_name == "hivemind_check_messages":
        peer = args.get("peer", "")
        if not peer:
            peers = await backend.get_peers()
            all_msgs = []
            for p in peers:
                msgs = await backend.get_messages_from_peer(p["name"])
                all_msgs.append({"peer": p["name"], "messages": msgs})
            return all_msgs
        return await backend.get_messages_from_peer(peer)

    if tool_name == "hivemind_send_to_peer":
        await backend.get_peers()
        await backend.send_to_peer(args["peer"], args["message"])
        return {"sent": True, "to": args["peer"]}

    if tool_name == "hivemind_get_peer_info":
        peers = await backend.get_peers()
        for p in peers:
            if p["name"] == args["peer"] or args["peer"] in p["name"]:
                return p
        return {"error": f"Unknown peer: {args['peer']}"}

    if tool_name == "hivemind_introduce_peers":
        await backend.get_peers()
        meta_a = backend.get_peer_meta(args["peer_a"])
        meta_b = backend.get_peer_meta(args["peer_b"])
        assert meta_a, f"Unknown peer: {args['peer_a']}"
        assert meta_b, f"Unknown peer: {args['peer_b']}"
        summary_a = await backend._get_account_data(meta_a["room_id"], SUMMARY_KEY)
        summary_b = await backend._get_account_data(meta_b["room_id"], SUMMARY_KEY)
        context_a = summary_a["summary_text"] if summary_a else meta_a.get("context", "")
        context_b = summary_b["summary_text"] if summary_b else meta_b.get("context", "")
        await backend.create_introduction_room(
            meta_a["peer_id"], meta_b["peer_id"], context_a, context_b,
            reason=args.get("reason", ""),
        )
        await _update_spark_status(backend, args["peer_a"], args["peer_b"], "executed")
        return {"introduced": True, "peer_a": args["peer_a"], "peer_b": args["peer_b"]}

    if tool_name == "hivemind_dismiss_spark":
        await _update_spark_status(backend, args["peer_a"], args["peer_b"], "dismissed")
        return {"dismissed": True, "peer_a": args["peer_a"], "peer_b": args["peer_b"]}

    raise ValueError(f"Unknown tool: {tool_name}")


# -- Provider --

class HiveMindProvider(MemoryProvider):

    @property
    def name(self):
        return "hivemind"

    def __init__(self):
        self._backend = None
        self._cached_prefetch = ""

    def is_available(self):
        return all(os.environ.get(k) for k in
                   ["MATRIX_HOMESERVER", "MATRIX_USER_ID", "MATRIX_ACCESS_TOKEN"])

    def initialize(self, session_id, **kwargs):
        Backend = _get_backend_class()
        self._backend = Backend(
            os.environ["MATRIX_HOMESERVER"],
            os.environ["MATRIX_USER_ID"],
            os.environ["MATRIX_ACCESS_TOKEN"],
        )
        _run_async(self._backend.get_peers())

    def system_prompt_block(self):
        return SYSTEM_PROMPT

    def prefetch(self, query, *, session_id=""):
        peers = _run_async(self._backend.get_peers())
        try:
            suggestions = _run_async(_maybe_update_and_spark(self._backend, peers))
        except Exception as e:
            logger.debug("Spark detection failed (non-fatal): %s", e)
            suggestions = []
        self._cached_prefetch = _format_context(peers, suggestions)
        return self._cached_prefetch

    def get_tool_schemas(self):
        return list(ALL_TOOLS)

    def handle_tool_call(self, tool_name, args, **kwargs):
        return json.dumps(_run_async(_dispatch(self._backend, tool_name, args)))

    def shutdown(self):
        if self._backend:
            _run_async(self._backend.close())

    def get_config_schema(self):
        return [
            {"key": "homeserver", "description": "Matrix homeserver URL", "required": True},
            {"key": "user_id", "description": "Matrix user ID (@hermes-of-bob:localhost)", "required": True},
            {"key": "access_token", "description": "Matrix access token", "required": True, "secret": True,
             "env_var": "MATRIX_ACCESS_TOKEN"},
        ]


def register(ctx):
    ctx.register_memory_provider(HiveMindProvider())
