import asyncio

import pytest

from fake_relay import DEVICE_ID, MEDIA_KEY, UID, FakeRelay, relay_token, signer
from tuya_ipc_p2p_sdk.exceptions import (
    TuyaIpcP2pConnectionError,
    TuyaIpcP2pProtocolError,
    TuyaIpcP2pSessionError,
)
from tuya_ipc_p2p_sdk.transport.kcp_segment import CMD_PUSH, build_segment, parse_segment
from tuya_ipc_p2p_sdk.transport.relay_connection import RelayConnection
from tuya_ipc_p2p_sdk.transport.relay_framing import relay_frame
from tuya_ipc_p2p_sdk.transport.relay_session import RelaySession


@pytest.fixture
async def relay():
    server = FakeRelay()
    await server.start()
    yield server
    await server.stop()


async def test_a_connection_completes_the_handshake_and_carries_segments(relay):
    connection = RelayConnection(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    segments: list[bytes] = []
    connection.set_segment_handler(segments.append)
    await connection.async_connect()
    await asyncio.wait_for(relay.handshaken.wait(), 2)

    connection.write_segment(b"client-segment")
    await asyncio.sleep(0.05)
    assert relay.received == [b"client-segment"]

    relay.send_segment(b"device-segment")
    await asyncio.sleep(0.05)
    assert segments == [b"device-segment"]
    await connection.async_close()


async def test_the_keepalive_and_unknown_frames_are_skipped(relay):
    connection = RelayConnection(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    segments: list[bytes] = []
    connection.set_segment_handler(segments.append)
    await connection.async_connect()
    await asyncio.wait_for(relay.handshaken.wait(), 2)

    relay.send_raw(relay_frame(0xF5, b""))
    relay.send_raw(relay_frame(0xF1, b"unknown"))
    relay.send_segment(b"real")
    await asyncio.sleep(0.05)
    assert segments == [b"real"]
    await connection.async_close()


async def test_a_device_signature_that_does_not_verify_fails_the_handshake():
    server = FakeRelay(reject_signature=True)
    await server.start()
    connection = RelayConnection(relay_token(server.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    with pytest.raises(TuyaIpcP2pProtocolError, match="device signature mismatch"):
        await connection.async_connect()
    await server.stop()


async def test_a_credential_too_short_to_key_the_handshake_is_rejected():
    token = relay_token(1)
    short = type(token)(token.urls, token.username, "short", token.session_id, token.raw)
    connection = RelayConnection(short, signer(), DEVICE_ID, UID, MEDIA_KEY)
    with pytest.raises(TuyaIpcP2pProtocolError, match="credential too short"):
        await connection.async_connect()


async def test_an_unreachable_relay_is_a_connection_error(unused_tcp_port):
    token = relay_token(unused_tcp_port)
    connection = RelayConnection(token, signer(), DEVICE_ID, UID, MEDIA_KEY)
    with pytest.raises(TuyaIpcP2pConnectionError):
        await connection.async_connect()


async def test_closing_a_connection_notifies_once(relay):
    connection = RelayConnection(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    closes: list[Exception | None] = []
    connection.set_close_handler(closes.append)
    await connection.async_connect()
    await connection.async_close()
    await connection.async_close()
    assert closes == [None]


async def test_a_session_routes_the_video_conversation_and_tunnels_signaling(relay):
    session = RelaySession(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    await session.async_connect()
    await asyncio.wait_for(relay.handshaken.wait(), 2)

    session.send_tunnel_frame(MEDIA_KEY, b'{"header":{}}')
    await asyncio.sleep(0.05)
    tunnelled = [
        parse_segment(raw)
        for raw in relay.received
        if (segment := parse_segment(raw)) is not None and segment.conversation == 0x010000F3
    ]
    assert tunnelled and tunnelled[0] is not None
    assert tunnelled[0].command == CMD_PUSH

    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 0, 0, b"video-record"))
    video = await asyncio.wait_for(session.async_wait_for_video(2), 2)
    records: list[bytes] = []
    video.set_message_handler(records.append)

    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 1, 0, b"second-record"))
    await asyncio.sleep(0.05)
    assert records == [b"second-record"]
    await session.async_close()


async def test_a_session_without_a_video_conversation_times_out(relay):
    session = RelaySession(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    await session.async_connect()
    with pytest.raises(TuyaIpcP2pSessionError, match="no video conversation"):
        await session.async_wait_for_video(0.05)
    await session.async_close()


async def test_a_session_reports_the_transport_going_away(relay):
    session = RelaySession(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    closes: list[Exception | None] = []
    session.set_close_handler(closes.append)
    await session.async_connect()
    await asyncio.wait_for(relay.handshaken.wait(), 2)
    await relay.stop()
    await asyncio.sleep(0.2)
    assert len(closes) == 1
    await session.async_close()


async def test_the_signaling_tunnel_splits_a_long_message_into_records(relay):
    session = RelaySession(relay_token(relay.port), signer(), DEVICE_ID, UID, MEDIA_KEY)
    await session.async_connect()
    await asyncio.wait_for(relay.handshaken.wait(), 2)

    session.send_tunnel_frame(MEDIA_KEY, b"x" * 3000)
    await asyncio.sleep(0.05)
    records = [
        segment
        for raw in relay.received
        if (segment := parse_segment(raw)) is not None and segment.conversation == 0x010000F3
    ]
    assert len(records) == 3
    assert [record.sequence for record in records] == [0, 1, 2]
    await session.async_close()
