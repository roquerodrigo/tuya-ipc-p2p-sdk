import pytest

from tuya_ipc_p2p_sdk.crypto import hmac_sha256
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.transport.relay_framing import (
    FRAME_MEDIA,
    assemble_handshake_frame,
    keepalive_frame,
    media_frame,
    media_tag,
    parse_handshake_frame,
    relay_frame,
    unwrap_media_frame,
)

KEY = b"0123456789abcdef"
MEDIA_KEY = b"fedcba9876543210"
IV = bytes(range(16))


def test_relay_frame_carries_its_own_length():
    frame = relay_frame(0xF4, b"payload")
    assert frame[0] == 0xF4
    assert frame[1] == 0x00
    assert int.from_bytes(frame[2:4], "big") == len(b"payload")
    assert frame[4:] == b"payload"


def test_the_keepalive_is_a_bare_header():
    assert keepalive_frame() == bytes.fromhex("f5000000")


def test_a_media_frame_round_trips_and_is_tagged():
    segment = b"kcp-segment-bytes"
    frame = media_frame(MEDIA_KEY, segment)
    assert frame[0] == FRAME_MEDIA
    assert unwrap_media_frame(MEDIA_KEY, frame[4:]) == segment
    assert frame[-20:] == media_tag(MEDIA_KEY, segment)


def test_a_media_frame_with_the_wrong_tag_is_rejected():
    frame = bytearray(media_frame(MEDIA_KEY, b"kcp-segment-bytes"))
    frame[-1] ^= 0xFF
    with pytest.raises(TuyaIpcP2pProtocolError, match="tag mismatch"):
        unwrap_media_frame(MEDIA_KEY, bytes(frame[4:]))


@pytest.mark.parametrize(
    "payload",
    [b"", b"\x00\x07\x00\x02" + bytes(2), b"\x00\x07\xff\xff" + bytes(40)],
)
def test_a_malformed_media_frame_is_rejected(payload):
    with pytest.raises(TuyaIpcP2pProtocolError):
        unwrap_media_frame(MEDIA_KEY, payload)


def test_a_handshake_frame_round_trips():
    message = b'{"method":"request"}'
    frame = assemble_handshake_frame(0, KEY, IV, b"session-id", b"user:name", message)
    assert frame[0] == 0xF4
    assert int.from_bytes(frame[2:4], "big") == len(frame) - 4
    assert parse_handshake_frame(KEY, frame[4:]) == {"method": "request"}


def test_a_handshake_frame_is_authenticated_up_to_the_digest():
    frame = assemble_handshake_frame(2, KEY, IV, b"session-id", b"user:name", b"{}")
    assert frame[-32:] == hmac_sha256(KEY, frame[:-32])
    assert frame[-36:-32] == b"\x00\x08\x00\x20"


def test_a_handshake_frame_without_an_encrypted_section_is_rejected():
    with pytest.raises(TuyaIpcP2pProtocolError, match="encrypted section"):
        parse_handshake_frame(KEY, bytes(8) + b"\x00\x00\x00\x00")


def test_a_handshake_frame_with_a_truncated_tlv_is_rejected():
    with pytest.raises(TuyaIpcP2pProtocolError, match="truncated TLV"):
        parse_handshake_frame(KEY, bytes(8) + b"\x00\x02\x00\xff" + bytes(4))
