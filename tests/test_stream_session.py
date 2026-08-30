import asyncio

import pytest

import fake_mqtt
from fake_relay import MEDIA_KEY, FakeRelay
from test_media import jpeg, media_packet, record
from tuya_ipc_p2p_sdk.crypto import aes_ecb_encrypt, encrypt_record
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pDeviceBusyError, TuyaIpcP2pSessionError
from tuya_ipc_p2p_sdk.json_types import dump_json
from tuya_ipc_p2p_sdk.models import MqttIdentity, StreamConfig
from tuya_ipc_p2p_sdk.signaling.envelope import encode_frame
from tuya_ipc_p2p_sdk.stream_session import StreamSession
from tuya_ipc_p2p_sdk.transport.kcp_segment import CMD_PUSH, build_segment

DEVICE_ID = "exampledevice000000001"
UID = "exampleuid0000000001"
LOCAL_KEY = "0123456789abcdef"
SESSION_ID = "exampledevice0000000011700000000AbCdEfGh"
ANSWER_KEY = bytes.fromhex("0f0e0d0c0b0a09080706050403020100")
IDENTITY = MqttIdentity("m1-us.lifeaiot.com", 8883, "client-id", "username", "password")

ANSWER_SDP = "\r\n".join(
    (
        "v=0",
        "m=application 9 tuya 6001",
        "a=ice-ufrag:Zi25",
        "a=ice-pwd:zhlW36t6BI2HxURDda1vmcla",
        f"a=aes-key:{ANSWER_KEY.hex()}",
    )
)


def stream_config(port: int) -> StreamConfig:
    return StreamConfig.from_json(
        {
            "id": DEVICE_ID,
            "motoId": "signaling3",
            "password": "abcd1234",
            "p2pConfig": {
                "session": {
                    "sessionId": SESSION_ID,
                    "aesKey": MEDIA_KEY.hex(),
                    "iceUfrag": "UfRg",
                    "icePassword": "zhlW36t6BI2HxURDda1vmcla",
                    "traceId": "trace",
                },
                "ices": [{"urls": "stun:stun.example:3478"}],
                "tcpRelay": {
                    "urls": [f"tcp4:127.0.0.1:{port}"],
                    "username": "1700036000:" + DEVICE_ID,
                    "credential": "AAAABBBBCCCCDDDDEEEEFFFFGGGG",
                    "sessionId": "server-minted-session-id",
                },
                "log": {"level": 2},
            },
        },
        DEVICE_ID,
        LOCAL_KEY,
    )


def signaling_payload(message_type: str, message: dict[str, object]) -> bytes:
    data = {"header": {"type": message_type, "sessionid": SESSION_ID}, "msg": message}
    plain = dump_json({"data": data, "protocol": 302, "t": 1700000000})
    return encode_frame(1, bytes(4), aes_ecb_encrypt(LOCAL_KEY.encode(), plain))


async def wait_for(predicate, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


@pytest.fixture
def broker(monkeypatch):
    fake_mqtt.install(monkeypatch, "tuya_ipc_p2p_sdk.signaling.moto_client")
    return fake_mqtt.FakeMqttClient


@pytest.fixture
async def relay():
    server = FakeRelay()
    await server.start()
    yield server
    await server.stop()


async def test_a_session_streams_a_frame_end_to_end(broker, relay):
    frames: list[bytes] = []
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, frames.append)
    start = asyncio.create_task(session.async_start())

    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("answer", {"sdp": ANSWER_SDP}))

    await wait_for(lambda: relay.handshaken.is_set())
    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 0, 0, b"opening"))
    await start

    image = jpeg(600)
    plaintext = record(media_packet(1, 0, image))
    relay.send_segment(
        build_segment(1, CMD_PUSH, 0, 512, 0, 1, 0, encrypt_record(ANSWER_KEY, plaintext))
    )
    relay.send_segment(
        build_segment(
            1,
            CMD_PUSH,
            0,
            512,
            0,
            2,
            0,
            encrypt_record(ANSWER_KEY, record(media_packet(2, 0, image))),
        )
    )
    await wait_for(lambda: frames)
    assert frames == [image]
    assert session.frame_count == 1
    await session.async_close()


async def test_the_offer_carries_a_freshly_minted_rendezvous_id(broker, relay):
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)

    from tuya_ipc_p2p_sdk.crypto import aes_ecb_decrypt
    from tuya_ipc_p2p_sdk.json_types import parse_json_object
    from tuya_ipc_p2p_sdk.signaling.envelope import decode_frame

    _topic, payload = broker.instances[-1].published[1]
    offer = parse_json_object(aes_ecb_decrypt(LOCAL_KEY.encode(), decode_frame(payload).body))
    message = offer["data"]["msg"]
    token = message["tcp_token"]
    assert token["sessionId"] != "server-minted-session-id"
    assert token["sessionId"].startswith(DEVICE_ID)
    assert message["preconnect"] is True

    start.cancel()
    await session.async_close()


async def test_a_device_that_never_answers_fails_the_session(broker, relay, monkeypatch):
    monkeypatch.setattr("tuya_ipc_p2p_sdk.stream_session._ANSWER_TIMEOUT_SECONDS", 0.1)
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    with pytest.raises(TuyaIpcP2pSessionError, match="no answer"):
        await session.async_start()
    await session.async_close()


async def test_a_device_disconnect_ends_the_session_before_it_starts(broker, relay):
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("disconnect", {"close_reason": 12}))

    with pytest.raises(TuyaIpcP2pDeviceBusyError, match="close_reason=12"):
        await start
    assert await session.async_wait_closed() == "device disconnect, close_reason=12"
    await session.async_close()


async def test_a_disconnect_that_is_not_busy_is_an_ordinary_session_error(broker, relay):
    """Only the busy reply says the device is holding a session."""
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("disconnect", {"close_reason": 4}))

    with pytest.raises(TuyaIpcP2pSessionError, match="close_reason=4") as raised:
        await start
    assert not isinstance(raised.value, TuyaIpcP2pDeviceBusyError)
    await session.async_close()


async def test_a_malformed_answer_fails_the_session(broker, relay):
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("answer", {"sdp": "v=0"}))
    with pytest.raises(Exception, match="Failed to parse answer"):
        await start
    await session.async_close()


async def test_the_relay_going_away_ends_the_session(broker, relay):
    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("answer", {"sdp": ANSWER_SDP}))
    await wait_for(lambda: relay.handshaken.is_set())
    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 0, 0, b"opening"))
    await start

    await relay.stop()
    reason = await asyncio.wait_for(session.async_wait_closed(), 3)
    assert "relay" in reason
    await session.async_close()


async def test_the_device_control_replies_are_drained(broker, relay):
    from tuya_ipc_p2p_sdk.control import build_command

    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("answer", {"sdp": ANSWER_SDP}))
    await wait_for(lambda: relay.handshaken.is_set())
    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 0, 0, b"opening"))
    await start

    reply = encrypt_record(ANSWER_KEY, build_command(0, 1, 0x0A, b"\x00\x00\x00\x00"))
    relay.send_segment(build_segment(0, CMD_PUSH, 0, 512, 0, 0, 0, reply))
    relay.send_segment(build_segment(0, CMD_PUSH, 0, 512, 0, 1, 0, b"undecryptable"))
    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 1, 0, b"undecryptable"))
    await asyncio.sleep(0.1)
    assert session.frame_count == 0
    await session.async_close()


async def test_the_start_burst_reaches_the_device(broker, relay):
    from tuya_ipc_p2p_sdk.transport.kcp_segment import parse_segment

    session = StreamSession(stream_config(relay.port), IDENTITY, UID, lambda _frame: None)
    start = asyncio.create_task(session.async_start())
    await wait_for(lambda: broker.instances and len(broker.instances[-1].published) >= 2)
    broker.instances[-1].deliver(signaling_payload("answer", {"sdp": ANSWER_SDP}))
    await wait_for(lambda: relay.handshaken.is_set())
    relay.send_segment(build_segment(1, CMD_PUSH, 0, 512, 0, 0, 0, b"opening"))
    await start
    await asyncio.sleep(0.1)

    control = [
        segment
        for raw in relay.received
        if (segment := parse_segment(raw)) is not None and segment.conversation == 0
    ]
    assert len(control) == 7
    await session.async_close()
