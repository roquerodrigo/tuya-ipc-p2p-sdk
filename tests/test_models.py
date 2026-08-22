import pytest

from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.models import RelayToken, StreamConfig

RAW_CONFIG = {
    "id": "exampledevice000000001",
    "motoId": "signaling3",
    "p2pType": 4,
    "password": "abcd1234",
    "p2pConfig": {
        "session": {
            "sessionId": "exampledevice0000000011700000000AbCdEfGh",
            "aesKey": "000102030405060708090a0b0c0d0e0f",
            "iceUfrag": "UfRg",
            "icePassword": "zhlW36t6BI2HxURDda1vmcla",
            "traceId": "11111111-2222-3333-4444-555555555555",
            "uid": "exampleuid0000000001",
        },
        "ices": [{"urls": "stun:stun.example:3478"}],
        "tcpRelay": {
            "urls": ["tcp4:10.0.0.9:1443"],
            "urlsEx": ["tcp6:[fe80::1]:1443"],
            "username": "1700036000:exampledevice000000001",
            "credential": "AAAABBBBCCCCDDDDEEEEFFFFGGGG",
            "sessionId": "exampledevice0000000011700036000ZzYyXxWw",
        },
        "log": {"level": 2},
    },
}


def test_a_stream_config_reads_the_whole_fetch():
    config = StreamConfig.from_json(RAW_CONFIG, "exampledevice000000001", "0123456789abcdef")
    assert config.device_password == "abcd1234"
    assert config.moto_id == "signaling3"
    assert config.local_key == "0123456789abcdef"
    assert config.p2p_session.aes_key.hex() == "000102030405060708090a0b0c0d0e0f"
    assert config.p2p_session.ice_ufrag == "UfRg"
    assert config.relay_token.endpoint == ("10.0.0.9", 1443)
    assert config.ice_servers_as_json() == [{"urls": "stun:stun.example:3478"}]
    assert config.log_config_as_json() == {"level": 2}


def test_a_config_without_a_p2p_section_is_rejected():
    with pytest.raises(TuyaIpcP2pProtocolError):
        StreamConfig.from_json({"id": "x"}, "x", "key")


def test_a_config_without_a_log_section_offers_an_empty_one():
    raw = {**RAW_CONFIG, "p2pConfig": {**RAW_CONFIG["p2pConfig"]}}
    del raw["p2pConfig"]["log"]
    config = StreamConfig.from_json(raw, "exampledevice000000001", "key")
    assert config.log_config_as_json() == {}


def test_the_offered_relay_token_replaces_only_the_rendezvous_id():
    token = RelayToken.from_json(RAW_CONFIG["p2pConfig"]["tcpRelay"])
    offered = token.offered("rendezvous-id")
    assert offered["sessionId"] == "rendezvous-id"
    assert offered["credential"] == token.credential
    assert token.session_id == "exampledevice0000000011700036000ZzYyXxWw"

    rebound = token.with_session_id("rendezvous-id")
    assert rebound.session_id == "rendezvous-id"
    assert rebound.as_json()["sessionId"] == "rendezvous-id"


def test_the_expire_timestamp_is_the_username_prefix():
    token = RelayToken.from_json(RAW_CONFIG["p2pConfig"]["tcpRelay"])
    assert token.expire_timestamp == "1700036000"


def test_a_relay_token_falls_back_to_the_ipv6_urls():
    raw = {**RAW_CONFIG["p2pConfig"]["tcpRelay"]}
    del raw["urls"]
    token = RelayToken.from_json(raw)
    assert token.endpoint == ("fe80::1", 1443)


def test_a_relay_token_without_urls_is_rejected():
    raw = {**RAW_CONFIG["p2pConfig"]["tcpRelay"], "urls": [], "urlsEx": []}
    with pytest.raises(TuyaIpcP2pProtocolError):
        RelayToken.from_json(raw)


def test_a_relay_url_without_a_port_falls_back_to_the_default():
    raw = {**RAW_CONFIG["p2pConfig"]["tcpRelay"], "urls": ["tcp4:10.0.0.9"]}
    assert RelayToken.from_json(raw).endpoint == ("10.0.0.9", 1443)
