import json, os, re, uuid
from datetime import datetime, timezone

import nio

PEER_ACCOUNT_DATA_KEY = "social.awareness.peer"

ENCRYPTION_EVENT = {
    "type": "m.room.encryption",
    "state_key": "",
    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
}


class MatrixBackend:
    def __init__(self, homeserver: str, user_id: str, access_token: str,
                 store_path: str = None, device_id: str = None):
        self.user_id = user_id
        store = store_path or os.path.join(
            os.environ.get("HERMES_HOME", os.path.expanduser("~/.hermes")),
            "nio_store", user_id.replace(":", "_").lstrip("@"))
        os.makedirs(store, exist_ok=True)
        config = nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)
        self.client = nio.AsyncClient(homeserver, user_id, store_path=store,
                                       config=config, device_id=device_id)
        self.client.access_token = access_token
        self.client.user_id = user_id
        self.next_batch = None
        self._peer_rooms = {}

    async def close(self):
        await self.client.close()

    # -- Crypto helpers --

    async def _post_sync_crypto(self):
        if self.client.should_upload_keys:
            await self.client.keys_upload()
        if self.client.should_query_keys:
            await self.client.keys_query()
        if self.client.should_claim_keys:
            await self.client.keys_claim(self.client.get_users_for_key_claiming())

    # -- Core Matrix operations --

    async def sync(self, timeout=0):
        resp = await self.client.sync(timeout)
        assert isinstance(resp, nio.SyncResponse), f"sync failed: {resp}"
        self.next_batch = resp.next_batch
        await self._post_sync_crypto()
        return resp

    async def _join(self, room_id):
        resp = await self.client.join(room_id)
        assert isinstance(resp, nio.JoinResponse), f"join failed: {resp}"
        return resp

    async def _get_messages(self, room_id, limit=50):
        path = f"/_matrix/client/v3/rooms/{room_id}/messages"
        params = f"?dir=b&limit={limit}"
        resp = await self.client.send("GET", path + params, headers=self._auth_headers())
        data = json.loads(await resp.read())
        return data.get("chunk", [])

    async def _get_members(self, room_id):
        # Use raw HTTP to get ALL members (joined + invited), not just joined
        path = f"/_matrix/client/v3/rooms/{room_id}/members"
        resp = await self.client.send("GET", path, headers=self._auth_headers())
        data = json.loads(await resp.read())
        return {e["state_key"]: e["content"]["membership"]
                for e in data.get("chunk", [])}

    async def _get_room_creator(self, room_id):
        resp = await self.client.room_get_state(room_id)
        assert isinstance(resp, nio.RoomGetStateResponse), f"room_get_state failed: {resp}"
        for e in resp.events:
            if e.get("type") == "m.room.create":
                return e.get("sender") or e.get("content", {}).get("creator")
        return None

    # -- Account data (no native nio support, use raw HTTP) --

    def _auth_headers(self, extra=None):
        h = {"Authorization": f"Bearer {self.client.access_token}"}
        if extra:
            h.update(extra)
        return h

    async def _put_account_data(self, room_id, key, value):
        path = f"/_matrix/client/v3/user/{self.user_id}/rooms/{room_id}/account_data/{key}"
        resp = await self.client.send("PUT", path, data=json.dumps(value),
                                       headers=self._auth_headers({"Content-Type": "application/json"}))
        return json.loads(await resp.read())

    async def _get_account_data(self, room_id, key):
        path = f"/_matrix/client/v3/user/{self.user_id}/rooms/{room_id}/account_data/{key}"
        resp = await self.client.send("GET", path, headers=self._auth_headers())
        if resp.status == 404:
            return None
        return json.loads(await resp.read())

    async def _put_global_account_data(self, key, value):
        path = f"/_matrix/client/v3/user/{self.user_id}/account_data/{key}"
        resp = await self.client.send("PUT", path, data=json.dumps(value),
                                       headers=self._auth_headers({"Content-Type": "application/json"}))
        return json.loads(await resp.read())

    async def _get_global_account_data(self, key):
        path = f"/_matrix/client/v3/user/{self.user_id}/account_data/{key}"
        resp = await self.client.send("GET", path, headers=self._auth_headers())
        if resp.status == 404:
            return None
        return json.loads(await resp.read())

    # -- Peer discovery --

    async def process_invites(self, sync_resp):
        new_peers = []
        for room_id in sync_resp.rooms.invite:
            await self._join(room_id)
            # Sync again to get room state after joining
            await self.sync()
            peer = await self._extract_peer_from_room(room_id)
            if peer:
                await self._put_account_data(room_id, PEER_ACCOUNT_DATA_KEY, peer)
                self._peer_rooms[room_id] = peer
                new_peers.append(peer)
        return new_peers

    async def _extract_peer_from_room(self, room_id):
        members = await self._get_members(room_id)
        creator = await self._get_room_creator(room_id)
        messages = await self._get_messages(room_id)

        other_members = [m for m in members
                         if m != self.user_id and m != creator]
        if not other_members:
            return None

        peer_id = other_members[0]

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
        sync_resp = await self.sync()
        await self.process_invites(sync_resp)

        peers = []
        seen_rooms = set()
        seen_peers = set()

        all_room_ids = list(sync_resp.rooms.join.keys()) + list(self._peer_rooms.keys())
        for room_id in all_room_ids:
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
        room_id = self._resolve_peer(peer_name)
        assert room_id, f"Unknown peer: {peer_name}"
        await self.sync()
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
        room_id = self._resolve_peer(peer_name)
        assert room_id, f"Unknown peer: {peer_name}"
        resp = await self.client.room_send(
            room_id, "m.room.message",
            {"msgtype": "m.text", "body": message},
            ignore_unverified_devices=True,
        )
        assert isinstance(resp, nio.RoomSendResponse), f"send failed: {resp}"
        return {"event_id": resp.event_id}

    async def create_introduction_room(self, peer_a_id, peer_b_id, context_a, context_b, reason=""):
        room_name = f"Introduction: {_extract_name(peer_a_id)} <> {_extract_name(peer_b_id)}"
        resp = await self.client.room_create(
            name=room_name,
            invite=[peer_a_id, peer_b_id],
            initial_state=[ENCRYPTION_EVENT],
        )
        assert isinstance(resp, nio.RoomCreateResponse), f"createRoom failed: {resp}"
        room_id = resp.room_id

        for body in [f"About {peer_a_id}: {context_a}",
                     f"About {peer_b_id}: {context_b}"] + \
                    ([f"Why: {reason}"] if reason else []):
            send_resp = await self.client.room_send(
                room_id, "m.room.message",
                {"msgtype": "m.text", "body": body},
                ignore_unverified_devices=True,
            )
            assert isinstance(send_resp, nio.RoomSendResponse), f"send failed: {send_resp}"

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
        name = peer_name.split("@")[0] if "@" in peer_name else peer_name
        for room_id, meta in self._peer_rooms.items():
            if meta.get("peer_name") == name or meta.get("peer_name") == peer_name:
                return room_id
            if meta.get("peer_id", "").startswith(f"@{name}"):
                return room_id
        return None


def _extract_name(matrix_id):
    if not matrix_id:
        return "unknown"
    return matrix_id.split(":")[0].lstrip("@")

def _format_peer(meta):
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
