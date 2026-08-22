import asyncio
import socket

import pytest

from tuya_ipc_p2p_sdk.transport.ice_responder import IceResponder, local_address

STUN_MAGIC_COOKIE = 0x2112A442


def binding_request(transaction_id: bytes) -> bytes:
    return (
        (0x0001).to_bytes(2, "big")
        + (0).to_bytes(2, "big")
        + STUN_MAGIC_COOKIE.to_bytes(4, "big")
        + transaction_id
    )


def candidate_port(candidate: str) -> int:
    return int(candidate.split(" ")[5])


async def test_the_responder_publishes_a_candidate_and_answers_binding_requests():
    candidates: list[str] = []
    responder = IceResponder("password", candidates.append)
    await responder.async_gather()
    assert len(candidates) == 1
    assert local_address() in candidates[0]

    port = candidate_port(candidates[0])
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.settimeout(2)
    try:
        transaction_id = b"0123456789ab"
        probe.sendto(binding_request(transaction_id), ("127.0.0.1", port))
        response = await asyncio.get_running_loop().run_in_executor(None, probe.recv, 1024)
    finally:
        probe.close()
    assert int.from_bytes(response[0:2], "big") == 0x0101
    assert response[8:20] == transaction_id
    responder.close()


@pytest.mark.parametrize(
    "payload",
    [b"too-short", b"\x00\x02" + bytes(18), (0x0001).to_bytes(2, "big") + bytes(18)],
)
async def test_anything_that_is_not_a_binding_request_is_ignored(payload):
    candidates: list[str] = []
    responder = IceResponder("password", candidates.append)
    await responder.async_gather()

    port = candidate_port(candidates[0])
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.settimeout(0.2)
    try:
        probe.sendto(payload, ("127.0.0.1", port))
        with pytest.raises(TimeoutError):
            await asyncio.get_running_loop().run_in_executor(None, probe.recv, 1024)
    finally:
        probe.close()
    responder.close()


async def test_a_closed_responder_stops_answering():
    responder = IceResponder("password", lambda _candidate: None)
    await responder.async_gather()
    responder.close()
    responder.datagram_received(binding_request(b"0123456789ab"), ("127.0.0.1", 1))
    responder.error_received(OSError("socket went away"))
    responder.close()
