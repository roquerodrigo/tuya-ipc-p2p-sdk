"""A relay server that speaks just enough of the protocol to drive the client."""

from __future__ import annotations

import asyncio
import secrets

from tuya_ipc_p2p_sdk.crypto import random_alphanumeric
from tuya_ipc_p2p_sdk.json_types import dump_json
from tuya_ipc_p2p_sdk.models import RelayToken
from tuya_ipc_p2p_sdk.signaling import HandshakeSigner, authorization_field
from tuya_ipc_p2p_sdk.transport.relay_framing import (
    FRAME_HANDSHAKE,
    assemble_handshake_frame,
    media_frame,
    parse_handshake_frame,
    unwrap_media_frame,
)

CREDENTIAL = "AAAABBBBCCCCDDDDEEEEFFFFGGGG"
DEVICE_ID = "exampledevice000000001"
UID = "exampleuid0000000001"
MEDIA_KEY = bytes.fromhex("000102030405060708090a0b0c0d0e0f")


def relay_token(port: int, session_id: str = "rendezvous-id") -> RelayToken:
    """The token the client dials the fake relay with."""
    return RelayToken.from_json(
        {
            "urls": [f"tcp4:127.0.0.1:{port}"],
            "username": f"1700036000:{DEVICE_ID}",
            "credential": CREDENTIAL,
            "sessionId": session_id,
        }
    )


def signer(session_id: str = "rendezvous-id") -> HandshakeSigner:
    """A signer bound to the same rendezvous as the token."""
    return HandshakeSigner(CREDENTIAL, "1700036000", DEVICE_ID, session_id, UID)


def handshake_tlv(payload: bytes, wanted: int) -> bytes:
    """Read one TLV out of a handshake frame body, which is where the ids ride."""
    cursor = 8
    while cursor + 4 <= len(payload):
        value_type = int.from_bytes(payload[cursor : cursor + 2], "big")
        length = int.from_bytes(payload[cursor + 2 : cursor + 4], "big")
        if value_type == 0 and length == 0:
            return b""
        if value_type == wanted:
            return payload[cursor + 4 : cursor + 4 + length]
        cursor += 4 + length
    return b""


class FakeRelay:
    """
    Accepts one connection, completes the handshake, then relays frames by hand.

    ``received`` collects the KCP segments the client wrote; ``send_segment``
    pushes one back the other way.
    """

    def __init__(self, *, reject_signature: bool = False) -> None:
        self.received: list[bytes] = []
        self.session_id = ""
        self.handshaken = asyncio.Event()
        self._reject_signature = reject_signature
        self._server: asyncio.Server | None = None
        self._writer: asyncio.StreamWriter | None = None
        self._task: asyncio.Task[None] | None = None
        self.port = 0

    async def start(self) -> int:
        server = await asyncio.start_server(self._handle, "127.0.0.1", 0)
        self._server = server
        self.port = int(server.sockets[0].getsockname()[1])
        return self.port

    async def _handle(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        self._writer = writer
        key = CREDENTIAL[:16].encode()
        payload = await self._read_payload(reader)
        request = parse_handshake_frame(key, payload)
        session_id = handshake_tlv(payload, 3)
        self.session_id = session_id.decode()
        client_random = authorization_field(str(request["authorization"]), "random")
        device_random = random_alphanumeric(32)
        signature = (
            "wrong-signature"
            if self._reject_signature
            else signer(self.session_id).device_signature(client_random)
        )
        writer.write(
            assemble_handshake_frame(
                1,
                key,
                secrets.token_bytes(16),
                session_id,
                f"1700036000:{DEVICE_ID}".encode(),
                dump_json(
                    {
                        "method": "response",
                        "authorization": f"signature={signature},random={device_random}",
                    }
                ),
            )
        )
        await writer.drain()
        if self._reject_signature:
            return

        await self._read_payload(reader)
        writer.write(
            assemble_handshake_frame(
                3,
                key,
                secrets.token_bytes(16),
                session_id,
                f"1700036000:{DEVICE_ID}".encode(),
                dump_json({"method": "complete", "statuscode": 200}),
            )
        )
        await writer.drain()
        self.handshaken.set()
        self._task = asyncio.create_task(self._collect(reader))

    async def _read_payload(self, reader: asyncio.StreamReader) -> bytes:
        while True:
            header = await reader.readexactly(4)
            length = int.from_bytes(header[2:4], "big")
            payload = await reader.readexactly(length) if length else b""
            if header[0] == FRAME_HANDSHAKE:
                return payload

    async def _collect(self, reader: asyncio.StreamReader) -> None:
        try:
            while True:
                header = await reader.readexactly(4)
                length = int.from_bytes(header[2:4], "big")
                payload = await reader.readexactly(length) if length else b""
                if header[0] == 0xF6:
                    self.received.append(unwrap_media_frame(MEDIA_KEY, payload))
        except (asyncio.IncompleteReadError, ConnectionError, asyncio.CancelledError):
            return

    def send_segment(self, segment: bytes) -> None:
        if self._writer is not None:
            self._writer.write(media_frame(MEDIA_KEY, segment))

    def send_raw(self, frame: bytes) -> None:
        if self._writer is not None:
            self._writer.write(frame)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
        if self._writer is not None:
            self._writer.close()
        if self._server is not None:
            self._server.close()
            await self._server.wait_closed()
