import os, tempfile
import nio

ENCRYPTION_EVENT = {
    "type": "m.room.encryption",
    "state_key": "",
    "content": {"algorithm": "m.megolm.v1.aes-sha2"},
}

class MatrixIntroducer:
    def __init__(self, homeserver: str, user_id: str, access_token: str,
                 store_path: str = None):
        store = store_path or tempfile.mkdtemp(prefix="introducer_")
        config = nio.AsyncClientConfig(encryption_enabled=True, store_sync_tokens=True)
        self.client = nio.AsyncClient(homeserver, user_id, store_path=store, config=config)
        self.client.access_token = access_token
        self.client.user_id = user_id

    async def _sync_crypto(self):
        resp = await self.client.sync(timeout=0)
        assert isinstance(resp, nio.SyncResponse), f"sync failed: {resp}"
        if self.client.should_upload_keys:
            await self.client.keys_upload()
        if self.client.should_query_keys:
            await self.client.keys_query()
        if self.client.should_claim_keys:
            await self.client.keys_claim(self.client.get_users_for_key_claiming())

    async def introduce(self, agent_b_id: str, agent_c_id: str,
                        context_b: str, context_c: str, room_name: str = None,
                        encrypted: bool = True):
        await self._sync_crypto()
        initial_state = [ENCRYPTION_EVENT] if encrypted else []
        resp = await self.client.room_create(
            name=room_name or f"Introduction: {agent_b_id} <> {agent_c_id}",
            invite=[agent_b_id, agent_c_id],
            initial_state=initial_state,
        )
        assert isinstance(resp, nio.RoomCreateResponse), f"room_create failed: {resp}"
        room_id = resp.room_id
        await self._sync_crypto()

        await self._send(room_id, f"About {agent_b_id}: {context_b}")
        await self._send(room_id, f"About {agent_c_id}: {context_c}")

        return {"room_id": room_id, "invited": [agent_b_id, agent_c_id]}

    async def _send(self, room_id: str, body: str):
        resp = await self.client.room_send(
            room_id, "m.room.message",
            {"msgtype": "m.text", "body": body},
            ignore_unverified_devices=True,
        )
        assert isinstance(resp, nio.RoomSendResponse), f"room_send failed: {resp}"
        return resp

    async def close(self):
        await self.client.close()
