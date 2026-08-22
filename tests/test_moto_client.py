import asyncio

import pytest

import fake_mqtt
from tuya_ipc_p2p_sdk.crypto import aes_ecb_decrypt, aes_ecb_encrypt
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pConnectionError
from tuya_ipc_p2p_sdk.json_types import dump_json, parse_json_object
from tuya_ipc_p2p_sdk.models import MqttIdentity
from tuya_ipc_p2p_sdk.signaling.envelope import decode_frame, encode_frame
from tuya_ipc_p2p_sdk.signaling.moto_client import MotoClient

LOCAL_KEY = "0123456789abcdef"
SESSION_ID = "exampledevice0000000011700000000AbCdEfGh"
IDENTITY = MqttIdentity("m1-us.lifeaiot.com", 8883, "client-id", "username", "password")


def inbound(message_type: str, message: dict[str, object], session_id: str = SESSION_ID) -> bytes:
    """Encode one payload the way the device sends it."""
    data = {
        "header": {"type": message_type, "sessionid": session_id, "from": "device"},
        "msg": message,
    }
    plain = dump_json({"data": data, "protocol": 302, "t": 1700000000})
    return encode_frame(1, bytes(4), aes_ecb_encrypt(LOCAL_KEY.encode(), plain))


class Recorder:
    def __init__(self) -> None:
        self.answers: list[str] = []
        self.candidates: list[str] = []
        self.disconnects: list[int] = []


@pytest.fixture
def recorder():
    return Recorder()


@pytest.fixture
def client(monkeypatch, recorder):
    fake_mqtt.install(monkeypatch, "tuya_ipc_p2p_sdk.signaling.moto_client")
    return MotoClient(
        identity=IDENTITY,
        uid="exampleuid0000000001",
        device_id="exampledevice000000001",
        session_id=SESSION_ID,
        local_key=LOCAL_KEY,
        on_answer=recorder.answers.append,
        on_candidate=recorder.candidates.append,
        on_disconnect=recorder.disconnects.append,
    )


async def test_connecting_subscribes_to_the_inbound_topic(client):
    await client.async_connect()
    broker = fake_mqtt.FakeMqttClient.instances[-1]
    assert broker.subscribed == ["smart/mb/in/exampledevice000000001"]
    assert broker.kwargs["identifier"] == "client-id"
    await client.async_close()
    assert broker.closed is True


async def test_a_broker_that_refuses_is_a_connection_error(client):
    fake_mqtt.FakeMqttClient.fail_on_connect = True
    with pytest.raises(TuyaIpcP2pConnectionError):
        await client.async_connect()


async def test_publishing_before_connecting_is_refused(client):
    with pytest.raises(TuyaIpcP2pConnectionError):
        await client.async_send_sig_query()


async def test_a_broker_that_drops_a_publish_is_a_connection_error(client):
    await client.async_connect()
    fake_mqtt.FakeMqttClient.fail_on_publish = True
    with pytest.raises(TuyaIpcP2pConnectionError):
        await client.async_send_sig_query()
    await client.async_close()


async def test_the_offer_carries_the_session_and_the_relay_token(client):
    await client.async_connect()
    await client.async_send_sig_query()
    await client.async_send_offer("v=0", [{"urls": "stun:x"}], "trace", {"sessionId": "r"}, {})
    await client.async_send_candidate("a=candidate:1 …")
    await client.async_send_disconnect()

    broker = fake_mqtt.FakeMqttClient.instances[-1]
    topics = {topic for topic, _payload in broker.published}
    assert topics == {"smart/mb/out/exampledevice000000001"}

    payloads = [
        parse_json_object(aes_ecb_decrypt(LOCAL_KEY.encode(), decode_frame(payload).body))
        for _topic, payload in broker.published
    ]
    assert payloads[0]["protocol"] == 22
    offer = payloads[1]["data"]
    assert isinstance(offer, dict)
    header = offer["header"]
    message = offer["msg"]
    assert isinstance(header, dict)
    assert isinstance(message, dict)
    assert header["type"] == "offer"
    assert header["p2p_skill"] == 1635
    assert header["trace_id"] == "trace"
    assert message["tcp_token"] == {"sessionId": "r"}
    assert payloads[2]["data"]["header"]["type"] == "candidate"
    assert payloads[3]["data"]["msg"]["close_reason"] == 4
    await client.async_close()


async def test_inbound_messages_reach_their_callbacks(client, recorder):
    await client.async_connect()
    broker = fake_mqtt.FakeMqttClient.instances[-1]
    broker.deliver(inbound("answer", {"sdp": "v=0"}))
    broker.deliver(inbound("candidate", {"candidate": "a=candidate:1 …"}))
    broker.deliver(inbound("disconnect", {"close_reason": 6}))
    await asyncio.sleep(0.05)
    assert recorder.answers == ["v=0"]
    assert recorder.candidates == ["a=candidate:1 …"]
    assert recorder.disconnects == [6]
    await client.async_close()


async def test_payloads_for_another_session_or_of_another_shape_are_discarded(client, recorder):
    await client.async_connect()
    broker = fake_mqtt.FakeMqttClient.instances[-1]
    broker.deliver(inbound("answer", {"sdp": "v=0"}, session_id="another-session"))
    broker.deliver(inbound("answer", {}))
    broker.deliver(inbound("unknown", {"sdp": "v=0"}))
    broker.deliver(b"not-an-envelope")
    broker.deliver(
        encode_frame(1, bytes(4), aes_ecb_encrypt(LOCAL_KEY.encode(), b'{"data":{"header":1}}'))
    )
    await asyncio.sleep(0.05)
    assert recorder.answers == []
    assert recorder.disconnects == []
    await client.async_close()
