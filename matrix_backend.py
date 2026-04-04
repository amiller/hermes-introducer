import aiohttp, uuid, re
from datetime import datetime, timezone

PEER_ACCOUNT_DATA_KEY = "social.awareness.peer"

class MatrixBackend:
    def __init__(self, homeserver: str, user_id: str, access_token: str):
        self.homeserver = homeserver
        self.user_id = user_id
        self.token = access_token
        self.next_batch = None
        self.session = None
        self._peer_rooms = {}  # room_id → peer metadata

    async def _ensure_session(self):
        if not self.session:
            self.session = aiohttp.ClientSession(
                headers={"Authorization": f"Bearer {self.token}"}
            )

    async def close(self):
        if self.session:
            await self.session.close()
            self.session = None

    async def sync(self, timeout=0):
        await self._ensure_session()
        params = {"timeout": str(timeout)}
        if self.next_batch:
            params["since"] = self.next_batch
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/sync", params=params,
        ) as resp:
            data = await resp.json()
            assert "next_batch" in data, f"sync failed: {data}"
            self.next_batch = data["next_batch"]
            return data

    async def _join(self, room_id):
        await self._ensure_session()
        async with self.session.post(
            f"{self.homeserver}/_matrix/client/v3/join/{room_id}", json={},
        ) as resp:
            data = await resp.json()
            assert "room_id" in data, f"join failed: {data}"
            return data

    async def _get_messages(self, room_id, limit=50):
        await self._ensure_session()
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/messages",
            params={"dir": "b", "limit": str(limit)},
        ) as resp:
            data = await resp.json()
            return data.get("chunk", [])

    async def _get_members(self, room_id):
        await self._ensure_session()
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/members",
        ) as resp:
            data = await resp.json()
            return {e["state_key"]: e["content"]["membership"]
                    for e in data.get("chunk", [])}

    async def _get_room_creator(self, room_id):
        await self._ensure_session()
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/state",
        ) as resp:
            events = await resp.json()
            for e in events:
                if e.get("type") == "m.room.create":
                    return e.get("sender") or e.get("content", {}).get("creator")
            return None

    async def _put_account_data(self, room_id, key, value):
        await self._ensure_session()
        async with self.session.put(
            f"{self.homeserver}/_matrix/client/v3/user/{self.user_id}/rooms/{room_id}/account_data/{key}",
            json=value,
        ) as resp:
            return await resp.json()

    async def _get_account_data(self, room_id, key):
        await self._ensure_session()
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/user/{self.user_id}/rooms/{room_id}/account_data/{key}",
        ) as resp:
            if resp.status == 404:
                return None
            return await resp.json()

    async def _put_global_account_data(self, key, value):
        await self._ensure_session()
        async with self.session.put(
            f"{self.homeserver}/_matrix/client/v3/user/{self.user_id}/account_data/{key}",
            json=value,
        ) as resp:
            return await resp.json()

    async def _get_global_account_data(self, key):
        await self._ensure_session()
        async with self.session.get(
            f"{self.homeserver}/_matrix/client/v3/user/{self.user_id}/account_data/{key}",
        ) as resp:
            if resp.status == 404:
                return None
            return await resp.json()

    async def process_invites(self, sync_data):
        """Auto-join pending invites and extract peer metadata."""
        invites = sync_data.get("rooms", {}).get("invite", {})
        new_peers = []
        for room_id in invites:
            await self._join(room_id)
            peer = await self._extract_peer_from_room(room_id)
            if peer:
                await self._put_account_data(room_id, PEER_ACCOUNT_DATA_KEY, peer)
                self._peer_rooms[room_id] = peer
                new_peers.append(peer)
        return new_peers

    async def _extract_peer_from_room(self, room_id):
        """Read room messages and members to figure out who our peer is and what the context says."""
        members = await self._get_members(room_id)
        creator = await self._get_room_creator(room_id)
        messages = await self._get_messages(room_id)

        other_members = [m for m in members
                         if m != self.user_id and m != creator]
        if not other_members:
            return None

        peer_id = other_members[0]

        # Extract context: look for "About @peer_id: ..." messages
        context = ""
        about_pattern = re.compile(rf"^About {re.escape(peer_id)}:\s*(.+)", re.DOTALL)
        for event in messages:
            if event.get("type") != "m.room.message":
                continue
            body = event.get("content", {}).get("body", "")
            match = about_pattern.match(body)
            if match:
                context = match.group(1).strip()
                break

        # Also grab context about US that the peer might want to know
        # (we extract what was said about the other person, not about us)

        return {
            "peer_name": _extract_name(peer_id),
            "peer_id": peer_id,
            "context": context,
            "introduced_by": _extract_name(creator) if creator else "unknown",
            "introduced_by_id": creator or "",
            "introduced_at": datetime.now(timezone.utc).isoformat(),
            "status": "active",
            "room_id": room_id,
        }

    async def get_peers(self):
        """Sync and return all known peers."""
        sync_data = await self.sync()
        await self.process_invites(sync_data)

        joined = sync_data.get("rooms", {}).get("join", {})
        peers = []
        seen_rooms = set()
        seen_peers = set()

        for room_id in list(joined.keys()) + list(self._peer_rooms.keys()):
            if room_id in seen_rooms:
                continue
            seen_rooms.add(room_id)
            meta = self._peer_rooms.get(room_id)
            if not meta:
                meta = await self._get_account_data(room_id, PEER_ACCOUNT_DATA_KEY)
            if not meta:
                meta = await self._extract_peer_from_room(room_id)
                if meta:
                    await self._put_account_data(room_id, PEER_ACCOUNT_DATA_KEY, meta)
            if meta:
                self._peer_rooms[room_id] = meta
                peer_id = meta.get("peer_id", "")
                if peer_id not in seen_peers:
                    seen_peers.add(peer_id)
                    peers.append(_format_peer(meta))

        return peers

    async def get_messages_from_peer(self, peer_name, limit=20):
        """Get recent messages from a specific peer's room."""
        room_id = self._resolve_peer(peer_name)
        assert room_id, f"Unknown peer: {peer_name}"
        events = await self._get_messages(room_id, limit)
        return [
            {
                "from": _extract_name(e["sender"]),
                "text": e["content"]["body"],
                "time": _ts_to_iso(e.get("origin_server_ts", 0)),
            }
            for e in events
            if e.get("type") == "m.room.message"
        ]

    async def send_to_peer(self, peer_name, message):
        """Send a message to a known peer."""
        room_id = self._resolve_peer(peer_name)
        assert room_id, f"Unknown peer: {peer_name}"
        await self._ensure_session()
        txn = uuid.uuid4().hex
        async with self.session.put(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
            json={"msgtype": "m.text", "body": message},
        ) as resp:
            data = await resp.json()
            assert "event_id" in data, f"send failed: {data}"
            return data

    async def create_introduction_room(self, peer_a_id, peer_b_id, context_a, context_b, reason=""):
        await self._ensure_session()
        room_name = f"Introduction: {_extract_name(peer_a_id)} <> {_extract_name(peer_b_id)}"
        async with self.session.post(
            f"{self.homeserver}/_matrix/client/v3/createRoom",
            json={"name": room_name, "invite": [peer_a_id, peer_b_id]},
        ) as resp:
            data = await resp.json()
            assert "room_id" in data, f"createRoom failed: {data}"
            room_id = data["room_id"]
        txn = uuid.uuid4().hex
        async with self.session.put(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
            json={"msgtype": "m.text", "body": f"About {peer_a_id}: {context_a}"},
        ) as resp:
            assert (await resp.json()).get("event_id"), "send context_a failed"
        txn = uuid.uuid4().hex
        async with self.session.put(
            f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
            json={"msgtype": "m.text", "body": f"About {peer_b_id}: {context_b}"},
        ) as resp:
            assert (await resp.json()).get("event_id"), "send context_b failed"
        if reason:
            txn = uuid.uuid4().hex
            async with self.session.put(
                f"{self.homeserver}/_matrix/client/v3/rooms/{room_id}/send/m.room.message/{txn}",
                json={"msgtype": "m.text", "body": f"Why: {reason}"},
            ) as resp:
                assert (await resp.json()).get("event_id"), "send reason failed"
        return {"room_id": room_id, "invited": [peer_a_id, peer_b_id]}

    def get_peer_meta(self, peer_name):
        name = peer_name.split("@")[0] if "@" in peer_name else peer_name
        for room_id, meta in self._peer_rooms.items():
            if meta.get("peer_name") == name or meta.get("peer_name") == peer_name:
                return meta
            if meta.get("peer_id", "").startswith(f"@{name}"):
                return meta
        return None

    def _resolve_peer(self, peer_name):
        """Find room_id for a peer by name. Accepts 'hermes-of-carol', 'hermes-of-carol@localhost', etc."""
        name = peer_name.split("@")[0] if "@" in peer_name else peer_name
        for room_id, meta in self._peer_rooms.items():
            if meta.get("peer_name") == name or meta.get("peer_name") == peer_name:
                return room_id
            if meta.get("peer_id", "").startswith(f"@{name}"):
                return room_id
        return None


def _extract_name(matrix_id):
    """@carol_abc123:localhost → carol_abc123"""
    if not matrix_id:
        return "unknown"
    return matrix_id.split(":")[0].lstrip("@")

def _format_peer(meta):
    """Convert stored metadata to agent-facing peer dict."""
    return {
        "name": meta.get("peer_name", "unknown"),
        "id": meta.get("peer_id", "").lstrip("@").replace(":", "@", 1) if meta.get("peer_id") else "unknown",
        "context": meta.get("context", ""),
        "introduced_by": meta.get("introduced_by", "unknown"),
        "introduced_at": meta.get("introduced_at", ""),
        "status": meta.get("status", "unknown"),
    }

def _ts_to_iso(ts_ms):
    return datetime.fromtimestamp(ts_ms / 1000, tz=timezone.utc).isoformat() if ts_ms else ""
