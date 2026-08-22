import re
from zlib import crc32

from tuya_ipc_p2p_sdk.crypto import hmac_sha1
from tuya_ipc_p2p_sdk.transport.ice_responder import (
    build_binding_success,
    candidate_line,
    local_address,
)

STUN_MAGIC_COOKIE = 0x2112A442


def test_binding_success_carries_the_transaction_id_and_a_xor_mapped_address():
    transaction_id = b"0123456789ab"
    response = build_binding_success(transaction_id, "192.168.5.106", 62238, "password")

    assert int.from_bytes(response[0:2], "big") == 0x0101
    assert int.from_bytes(response[4:8], "big") == STUN_MAGIC_COOKIE
    assert response[8:20] == transaction_id
    assert int.from_bytes(response[2:4], "big") == len(response) - 20

    assert int.from_bytes(response[20:22], "big") == 0x0020
    value = response[24:32]
    assert int.from_bytes(value[2:4], "big") ^ (STUN_MAGIC_COOKIE >> 16) == 62238
    address = (int.from_bytes(value[4:8], "big") ^ STUN_MAGIC_COOKIE).to_bytes(4, "big")
    assert ".".join(str(octet) for octet in address) == "192.168.5.106"


def test_message_integrity_and_fingerprint_verify_independently():
    # Both trailing attributes are computed over the message with its length
    # already extended to cover that attribute but not what follows it, so
    # recomputing them here pins the offsets.
    password = "zhlW36t6BI2HxURDda1vmcla"
    response = build_binding_success(bytes([7] * 12), "10.0.0.2", 1234, password)

    fingerprint_start = len(response) - 8
    integrity_start = fingerprint_start - 24
    assert int.from_bytes(response[integrity_start : integrity_start + 2], "big") == 0x0008
    assert int.from_bytes(response[fingerprint_start : fingerprint_start + 2], "big") == 0x8028

    integrity_input = bytearray(response[:integrity_start])
    integrity_input[2:4] = (integrity_start - 20 + 24).to_bytes(2, "big")
    assert response[integrity_start + 4 : integrity_start + 24] == hmac_sha1(
        password.encode(), bytes(integrity_input)
    )

    expected = (crc32(response[:fingerprint_start]) ^ 0x5354554E) & 0xFFFFFFFF
    assert (
        int.from_bytes(response[fingerprint_start + 4 : fingerprint_start + 8], "big") == expected
    )


def test_an_unresolvable_address_still_produces_a_valid_response():
    response = build_binding_success(bytes(12), "not-an-address", 1, "password")
    value = response[24:32]
    assert (int.from_bytes(value[4:8], "big") ^ STUN_MAGIC_COOKIE) == 0


def test_candidate_line_shape():
    line = candidate_line("192.168.5.5", 38193)
    assert re.fullmatch(r"a=candidate:\d+ 1 udp 2130706431 192\.168\.5\.5 38193 typ host\r\n", line)


def test_the_local_address_is_an_ipv4_address():
    assert re.fullmatch(r"\d+\.\d+\.\d+\.\d+", local_address())
