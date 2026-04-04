import os, uuid
from datetime import datetime, timezone
from pydantic import BaseModel
from fastmcp import FastMCP, Context
from matrix_backend import MatrixBackend

mcp = FastMCP("Social Awareness")

_backend = None

def _get_backend():
    global _backend
    if not _backend:
        _backend = MatrixBackend(
            os.environ["MATRIX_HOMESERVER"],
            os.environ["MATRIX_USER_ID"],
            os.environ["MATRIX_ACCESS_TOKEN"],
        )
    return _backend


# -- Pydantic models for structured sampling output --

class PeerSummary(BaseModel):
    needs: list[str]
    offers: list[str]
    expertise: list[str]
    summary_text: str

class SparkEvaluation(BaseModel):
    should_introduce: bool
    reason: str
    confidence: str


# -- Sampling helpers --

SUMMARY_KEY = "social.awareness.summary"
SPARKS_KEY = "social.awareness.sparks"
STALENESS_THRESHOLD = 5

async def _summarize_peer(ctx, peer_name, messages, context):
    msg_text = "\n".join(f"{m['from']}: {m['text']}" for m in messages[-30:])
    result = await ctx.sample(
        messages=f"Peer: {peer_name}\nIntroduction context: {context}\n\nRecent messages:\n{msg_text}",
        system_prompt=(
            "Analyze this peer based on their introduction context and messages. "
            "Extract what they NEED (problems, requests, gaps), what they OFFER "
            "(skills, services, knowledge), and their EXPERTISE areas. "
            "Be specific and concise. 2-4 items per category."
        ),
        result_type=PeerSummary,
        max_tokens=300,
    )
    return result.result.model_dump()

async def _detect_sparks(ctx, summaries):
    sparks = []
    for i, a in enumerate(summaries):
        for b in summaries[i+1:]:
            prompt = (
                f"Peer A — {a['peer_name']}:\n"
                f"  Needs: {', '.join(a['needs'])}\n"
                f"  Offers: {', '.join(a['offers'])}\n\n"
                f"Peer B — {b['peer_name']}:\n"
                f"  Needs: {', '.join(b['needs'])}\n"
                f"  Offers: {', '.join(b['offers'])}\n"
            )
            result = await ctx.sample(
                messages=prompt,
                system_prompt=(
                    "Evaluate whether two peers should be introduced. "
                    "An introduction is warranted when one peer's NEEDS match "
                    "another peer's OFFERS, or they have complementary expertise. "
                    "Be conservative — only suggest introductions with clear mutual benefit."
                ),
                result_type=SparkEvaluation,
                max_tokens=150,
            )
            ev = result.result
            if ev.should_introduce and ev.confidence in ("high", "medium"):
                sparks.append({
                    "peer_a": a["peer_name"],
                    "peer_b": b["peer_name"],
                    "reason": ev.reason,
                    "confidence": ev.confidence,
                })
    return sparks

async def _maybe_update_and_spark(ctx, backend, peers):
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
            formatted = [{"from": m.get("sender", ""), "text": m.get("content", {}).get("body", "")}
                         for m in messages if m.get("type") == "m.room.message"]
            new_summary = await _summarize_peer(ctx, peer["name"], formatted, peer.get("context", ""))
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
        new_sparks = await _detect_sparks(ctx, all_summaries)
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


# -- MCP Tools --

@mcp.tool()
async def list_peers(ctx: Context) -> dict:
    """List all agents you know, with context and introduction suggestions."""
    backend = _get_backend()
    peers = await backend.get_peers()
    suggestions = await _maybe_update_and_spark(ctx, backend, peers)
    return {"peers": peers, "suggestions": suggestions}

@mcp.tool()
async def check_messages(ctx: Context, peer: str = "") -> dict:
    """Check for new messages. Optionally filter by peer name."""
    backend = _get_backend()
    if not peer:
        peers = await backend.get_peers()
        all_msgs = []
        for p in peers:
            msgs = await backend.get_messages_from_peer(p["name"])
            all_msgs.append({"peer": p["name"], "messages": msgs})
        sparks_data = await backend._get_global_account_data(SPARKS_KEY) or {"sparks": []}
        suggestions = [s for s in sparks_data["sparks"] if s["status"] == "pending"]
        return {"messages": all_msgs, "suggestions": suggestions}
    return await backend.get_messages_from_peer(peer)

@mcp.tool()
async def send_to_peer(peer: str, message: str) -> dict:
    """Send a message to a known peer."""
    backend = _get_backend()
    await backend.get_peers()
    await backend.send_to_peer(peer, message)
    return {"sent": True, "to": peer}

@mcp.tool()
async def get_peer_info(peer: str) -> dict:
    """Get detailed information about a specific peer."""
    backend = _get_backend()
    peers = await backend.get_peers()
    for p in peers:
        if p["name"] == peer or peer in p["name"]:
            return p
    return {"error": f"Unknown peer: {peer}"}

@mcp.tool()
async def introduce_peers(ctx: Context, peer_a: str, peer_b: str, reason: str = "") -> dict:
    """Introduce two of your peers by creating a shared room with context."""
    backend = _get_backend()
    await backend.get_peers()
    meta_a = backend.get_peer_meta(peer_a)
    meta_b = backend.get_peer_meta(peer_b)
    assert meta_a, f"Unknown peer: {peer_a}"
    assert meta_b, f"Unknown peer: {peer_b}"

    summary_a = await backend._get_account_data(meta_a["room_id"], SUMMARY_KEY)
    summary_b = await backend._get_account_data(meta_b["room_id"], SUMMARY_KEY)
    context_a = summary_a["summary_text"] if summary_a else meta_a.get("context", "")
    context_b = summary_b["summary_text"] if summary_b else meta_b.get("context", "")

    room = await backend.create_introduction_room(
        meta_a["peer_id"], meta_b["peer_id"], context_a, context_b, reason=reason,
    )
    await _update_spark_status(backend, peer_a, peer_b, "executed")
    return {"introduced": True, "peer_a": peer_a, "peer_b": peer_b, "reason": reason}

@mcp.tool()
async def dismiss_spark(peer_a: str, peer_b: str) -> dict:
    """Dismiss a suggested introduction between two peers."""
    backend = _get_backend()
    await _update_spark_status(backend, peer_a, peer_b, "dismissed")
    return {"dismissed": True, "peer_a": peer_a, "peer_b": peer_b}

if __name__ == "__main__":
    mcp.run()
