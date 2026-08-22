import pytest

from tuya_ipc_p2p_sdk.control import (
    auth_credential,
    build_command,
    is_control,
    parse_control,
    start_sequence,
)
from tuya_ipc_p2p_sdk.crypto import decrypt_record, encrypt_record
from tuya_ipc_p2p_sdk.jpeg_reassembler import JpegReassembler
from tuya_ipc_p2p_sdk.media import extract_media_packets

HEADER_LENGTH = 20


def media_packet(frame_id: int, offset: int, payload: bytes) -> bytes:
    packet = bytearray(HEADER_LENGTH + len(payload))
    packet[0:2] = (len(payload) & 0xFFFF).to_bytes(2, "little")
    packet[4:8] = frame_id.to_bytes(4, "little")
    packet[8:12] = (0x0A).to_bytes(4, "little")
    packet[12:16] = offset.to_bytes(4, "big")
    packet[16:20] = b"\x00\xff\x50\x3c"
    packet[HEADER_LENGTH:] = payload
    return bytes(packet)


def jpeg(length: int) -> bytes:
    image = bytearray(length)
    image[0:2] = b"\xff\xd8"
    for index in range(2, length - 2):
        image[index] = index & 0xFF
    image[-2:] = b"\xff\xd9"
    return bytes(image)


def record(*packets: bytes) -> bytes:
    return b"".join(len(packet).to_bytes(4, "little") + packet for packet in packets)


def test_reassembles_a_frame_from_in_order_chunks():
    image = jpeg(2400)
    reassembler = JpegReassembler()
    chunk = 1150
    for offset in range(0, len(image), chunk):
        reassembler.push(media_packet(100, offset, image[offset : offset + chunk]))
    frame = reassembler.push(media_packet(101, 0, image[:chunk]))
    assert frame == image


def test_reassembles_out_of_order_chunks_by_offset():
    image = jpeg(2400)
    reassembler = JpegReassembler()
    chunk = 1150
    for offset in (0, 2300, 1150):
        reassembler.push(media_packet(200, offset, image[offset : offset + chunk]))
    assert reassembler.push(media_packet(201, 0, image[:chunk])) == image


def test_a_reset_reassembler_forgets_the_frame_in_progress():
    image = jpeg(2400)
    reassembler = JpegReassembler()
    reassembler.push(media_packet(1, 0, image[:1150]))
    reassembler.reset()
    assert reassembler.push(media_packet(2, 0, image[:1150])) is None


def test_a_header_only_packet_completes_nothing():
    assert JpegReassembler().push(bytes(HEADER_LENGTH)) is None


def test_extracts_one_media_packet_from_a_record():
    payload = jpeg(1150)
    packet = media_packet(0x1234, 0, payload)
    packets = extract_media_packets(record(packet))
    assert len(packets) == 1
    assert len(packets[0]) == len(packet)
    assert int.from_bytes(packets[0][12:16], "big") == 0
    assert packets[0][HEADER_LENGTH:] == payload


def test_extracts_several_media_packets_from_one_record():
    packets = extract_media_packets(
        record(media_packet(1, 0, jpeg(64)), media_packet(1, 64, jpeg(48)))
    )
    assert len(packets) == 2
    assert int.from_bytes(packets[1][12:16], "big") == 64


def test_records_with_no_media_packet_yield_nothing():
    assert extract_media_packets(bytes.fromhex("7856341201000000")) == []
    truncated = record(media_packet(1, 0, jpeg(64)))
    assert extract_media_packets(truncated[:-10]) == []


def test_channel_zero_auth_credential():
    assert auth_credential("abcd1234", "0123456789abcdef") == ("a48a3556709a48544ec8f1d42a9e9f87")


def test_start_sequence_layout():
    capability = (
        b'{"cmd":"capability_exchange_req","protocol_version":1,'
        b'"data":{"capabilities":{"opus_encode":1,"opus_decode":1}}}\x00'
    ).hex()
    want = [
        "78563412"
        "01000000"
        "61646d696e"
        "000000000000000000000000000000000000000000000000000000"
        "6134386133353536373039613438353434656338663164343261396539663837"
        "0000000000000000000000000000000000000000000000000000000000000000",
        "7856341200000000000000000a0000000400000001000100",
        "7856341200000000000000001500000071000000" + capability,
        "785634120200000000000000020000000400000000000000",
        "78563412040001000000000009000000080000000000000004000000",
        "78563412030001000000000006000000080000000000000000000000",
        "78563412050001000000000006000400080000000000000004000000",
    ]
    sequence = start_sequence(auth_credential("abcd1234", "0123456789abcdef"))
    assert [packet.hex() for packet in sequence] == want


def test_a_control_packet_round_trips_through_a_record():
    key = b"0123456789abcdef"
    original = build_command(0x00010004, 0, 0x09, bytes([0, 0, 0, 0, 4, 0, 0, 0]))
    plaintext = decrypt_record(key, encrypt_record(key, original))
    assert is_control(plaintext)
    packet = parse_control(plaintext)
    assert packet is not None
    assert packet.type == 0x00010004
    assert packet.sub_command == 0x09
    assert len(packet.payload) == 8


def test_a_control_packet_with_an_overlong_length_is_clamped():
    packet = parse_control(build_command(0, 0, 0, b"")[:20] + b"payload")
    assert packet is not None
    assert packet.payload == b""


def test_media_records_are_not_mistaken_for_control():
    plaintext = record(media_packet(1, 0, jpeg(64)))
    assert is_control(plaintext) is False
    assert parse_control(plaintext) is None


@pytest.mark.parametrize("plaintext", [b"", b"short"])
def test_short_plaintexts_are_neither_control_nor_media(plaintext):
    assert is_control(plaintext) is False
    assert parse_control(plaintext) is None
