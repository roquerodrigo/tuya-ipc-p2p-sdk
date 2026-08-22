import pytest

from tuya_ipc_p2p_sdk.crypto import aes_ecb_encrypt
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.json_types import parse_json_object
from tuya_ipc_p2p_sdk.signaling import (
    HandshakeSigner,
    authorization_field,
    build_auth_ack,
    build_auth_request,
    build_offer,
    parse_answer,
    relay_candidate_frame,
    relay_offer_frame,
)
from tuya_ipc_p2p_sdk.signaling.envelope import (
    decode_frame,
    decode_payload,
    encode_frame,
    encode_payload,
)

LOCAL_KEY = b"0123456789abcdef"


def test_signaling_envelope_vector():
    payload = (
        '{"protocol":302,"pv":"2.2","t":1700000000,"data":{"header":{"type":"offer"},"msg":{}}}'
    )
    want = (
        "322e322841b2050000000400000001ea755a246e67a8cc3e61dbdaf73c5ff5"
        "d16b70eb9fdecab88f58ebe333fd3bc99b0b853bab143cbd29db21f1dcb1ba"
        "ccbe454130944da5bb3dac257dab4987acf038d9e2020dd6a986d7561eef5e"
        "9de31e60787eb6d61f55b35238f5cee5f7c7"
    )
    source = bytes.fromhex("00000001")
    frame = encode_frame(4, source, aes_ecb_encrypt(LOCAL_KEY, payload.encode()))
    assert frame.hex() == want

    decoded = decode_frame(frame)
    assert decoded.sequence == 4
    assert decoded.source == source


def test_signaling_envelope_rejects_a_corrupted_frame():
    frame = bytearray(encode_frame(1, bytes(4), b"body-body-body!!"))
    frame[-1] ^= 0xFF
    with pytest.raises(TuyaIpcP2pProtocolError, match="crc32"):
        decode_frame(bytes(frame))


def test_signaling_envelope_rejects_a_foreign_frame():
    with pytest.raises(TuyaIpcP2pProtocolError, match=r"2\.2"):
        decode_frame(b"nope")


def test_payload_round_trips_through_the_envelope():
    data = {"header": {"type": "answer"}, "msg": {"sdp": "v=0"}}
    payload = encode_payload(LOCAL_KEY, 7, bytes(4), data, 1700000000, 302)
    assert decode_payload(LOCAL_KEY, payload) == data


def test_payload_without_a_data_object_is_rejected():
    payload = encode_frame(1, bytes(4), aes_ecb_encrypt(LOCAL_KEY, b'{"protocol":22}'))
    with pytest.raises(TuyaIpcP2pProtocolError, match="data"):
        decode_payload(LOCAL_KEY, payload)


def test_relay_handshake_signature_vectors():
    signer = HandshakeSigner(
        credential="AAAABBBBCCCCDDDDEEEEFFFFGGGG",
        expire_timestamp="1700036000",
        device_id="exampledevice000000001",
        session_id="exampledevice0000000011700000000AbCdEfGh",
        uid="exampleuid0000000001",
    )
    device_signature = signer.device_signature("clientrandom00000000000000000001")
    assert device_signature == ("41921395cd980b859d3e9ae8cc312f45af236d1cb97f19f44dad10b1c765cdb9")
    assert signer.ack_signature(device_signature, "devicerandom00000000000000000002") == (
        "3d9b7cb6fba4b4e0a1cd35086b5d5c53517641a1a7391374d20a051159974124"
    )


def test_handshake_signer_needs_a_credential():
    with pytest.raises(TuyaIpcP2pProtocolError):
        HandshakeSigner("", "1", "dev", "session", "uid")


def test_handshake_messages():
    request = parse_json_object(build_auth_request("dev1", "uid1", "RANDOM32"))
    assert request["method"] == "request"
    assert request["authorization"] == "random=RANDOM32"
    ack = parse_json_object(build_auth_ack("dev1", "uid1", "SIG"))
    assert ack["method"] == "ack"
    assert ack["statuscode"] == 200


def test_authorization_fields():
    authorization = "signature=abc123,random=xyz789"
    assert authorization_field(authorization, "signature") == "abc123"
    assert authorization_field(authorization, "random") == "xyz789"
    assert authorization_field(authorization, "missing") == ""


def test_offer_carries_the_session_credentials_and_key():
    aes_key = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    offer = build_offer("uid1", "session1", 1700000000, "UfRg", "PaSsWoRd", aes_key)
    assert offer.sdp.startswith("v=0\r\n")
    assert "m=application 9 imm 6001\r\n" in offer.sdp
    assert "a=rtpmap:6001 AES/KCP 330\r\n" in offer.sdp
    assert "a=ice-ufrag:UfRg\r\n" in offer.sdp
    assert "a=aes-key:000102030405060708090a0b0c0d0e0f\r\n" in offer.sdp
    assert "a=ssrc:0 cname:uid1\r\n" in offer.sdp
    assert offer.aes_key == aes_key


def test_answer_parsing():
    answer = parse_answer(
        "\r\n".join(
            (
                "v=0",
                "m=application 9 tuya 6001",
                "a=ice-ufrag:Zi25",
                "a=ice-pwd:zhlW36t6BI2HxURDda1vmcla",
                "a=aes-key:66567765683454775a784176754a4a4b",
                "a=rtpmap:6001 AES/KCP 3",
            )
        )
    )
    assert answer.ice_ufrag == "Zi25"
    assert answer.ice_password == "zhlW36t6BI2HxURDda1vmcla"
    assert answer.aes_key.hex() == "66567765683454775a784176754a4a4b"


def test_answer_parsing_rejects_a_truncated_answer():
    with pytest.raises(TuyaIpcP2pProtocolError, match="Failed to parse answer"):
        parse_answer("v=0\r\na=ice-ufrag:Zi25\r\n")


def test_relay_frames_are_tagged_as_the_relay_path():
    offer = parse_json_object(
        relay_offer_frame("uid", "dev", "session", "trace", "v=0", [], {}, {})
    )
    header = offer["header"]
    assert isinstance(header, dict)
    assert header["path"] == "relay"
    assert header["p2p_skill"] == 1635

    candidate = parse_json_object(
        relay_candidate_frame("uid", "dev", "session", "trace", "a=candidate:1 …")
    )
    candidate_header = candidate["header"]
    assert isinstance(candidate_header, dict)
    assert candidate_header["type"] == "candidate"
    assert candidate_header["path"] == "relay"
