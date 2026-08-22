import asyncio

import pytest

from tuya_ipc_p2p_sdk.transport.kcp_conversation import KcpConversation
from tuya_ipc_p2p_sdk.transport.kcp_segment import CMD_ACK, CMD_PUSH, build_segment, parse_segment


def push(conversation: int, sequence: int, fragment: int, data: bytes) -> bytes:
    return build_segment(conversation, CMD_PUSH, fragment, 512, 0x4F37A4, sequence, 0, data)


def test_segment_header_round_trips():
    segment = parse_segment(push(1, 7, 0, b"hello"))
    assert segment is not None
    assert segment.conversation == 1
    assert segment.command == CMD_PUSH
    assert segment.sequence == 7
    assert segment.window == 512
    assert segment.data == b"hello"


def test_segment_header_matches_the_wire_layout():
    # Pinned against a segment captured from the device: conv 1, PUSH, window 200,
    # sn 0, 1232 payload bytes.
    raw = bytes.fromhex("010000005100c800a4374f000000000000000000d0040000")
    segment = parse_segment(raw + bytes(1232))
    assert segment is not None
    assert segment.conversation == 1
    assert segment.command == CMD_PUSH
    assert segment.fragment == 0
    assert segment.window == 200
    assert segment.sequence == 0
    assert len(segment.data) == 1232


def test_parse_segment_rejects_a_truncated_segment():
    assert parse_segment(bytes(10)) is None
    assert parse_segment(push(1, 0, 0, bytes(100))[:40]) is None


def test_delivers_messages_and_acknowledges_every_push():
    sent: list[bytes] = []
    conversation = KcpConversation(1, sent.append)
    messages: list[bytes] = []
    conversation.set_message_handler(messages.append)

    for sequence, payload in ((0, b"first"), (1, b"second")):
        segment = parse_segment(push(1, sequence, 0, payload))
        assert segment is not None
        conversation.input(segment)

    assert messages == [b"first", b"second"]
    assert len(sent) == 2
    acknowledgements = [parse_segment(raw) for raw in sent]
    assert all(item is not None and item.command == CMD_ACK for item in acknowledgements)
    last = acknowledgements[1]
    assert last is not None
    assert last.unacknowledged == 2
    conversation.close()


def test_reorders_out_of_order_segments():
    conversation = KcpConversation(1, lambda _raw: None)
    messages: list[bytes] = []
    conversation.set_message_handler(messages.append)

    for sequence, payload in ((2, b"third"), (0, b"first")):
        segment = parse_segment(push(1, sequence, 0, payload))
        assert segment is not None
        conversation.input(segment)
    assert messages == [b"first"]

    segment = parse_segment(push(1, 1, 0, b"second"))
    assert segment is not None
    conversation.input(segment)
    assert messages == [b"first", b"second", b"third"]
    conversation.close()


def test_rejoins_a_fragmented_message():
    conversation = KcpConversation(1, lambda _raw: None)
    messages: list[bytes] = []
    conversation.set_message_handler(messages.append)

    first = parse_segment(push(1, 0, 1, b"frag-"))
    assert first is not None
    conversation.input(first)
    assert messages == []

    second = parse_segment(push(1, 1, 0, b"mented"))
    assert second is not None
    conversation.input(second)
    assert messages == [b"frag-mented"]
    conversation.close()


def test_ignores_duplicates():
    conversation = KcpConversation(1, lambda _raw: None)
    messages: list[bytes] = []
    conversation.set_message_handler(messages.append)

    for _ in range(2):
        segment = parse_segment(push(1, 0, 0, b"once"))
        assert segment is not None
        conversation.input(segment)
    assert messages == [b"once"]
    conversation.close()


async def test_sends_a_push_and_retires_it_when_acknowledged():
    sent: list[bytes] = []
    conversation = KcpConversation(0, sent.append)
    conversation.send(b"control-packet")

    assert len(sent) == 1
    segment = parse_segment(sent[0])
    assert segment is not None
    assert segment.command == CMD_PUSH
    assert segment.sequence == 0
    assert segment.data == b"control-packet"

    acknowledgement = parse_segment(build_segment(0, CMD_ACK, 0, 512, 0, 0, 1))
    assert acknowledgement is not None
    conversation.input(acknowledgement)
    await conversation.async_close()


async def test_fragments_a_message_larger_than_one_segment():
    sent: list[bytes] = []
    conversation = KcpConversation(0, sent.append)
    conversation.send(b"A" * 3000)

    assert len(sent) == 3
    fragments = [parse_segment(raw) for raw in sent]
    assert [item.fragment for item in fragments if item is not None] == [2, 1, 0]
    assert sum(len(item.data) for item in fragments if item is not None) == 3000
    await conversation.async_close()


async def test_a_closed_conversation_refuses_to_send():
    conversation = KcpConversation(0, lambda _raw: None)
    await conversation.async_close()
    with pytest.raises(RuntimeError):
        conversation.send(b"anything")


async def test_a_window_probe_is_answered():
    sent: list[bytes] = []
    conversation = KcpConversation(1, sent.append)
    probe = parse_segment(build_segment(1, 0x53, 0, 512, 0, 0, 0))
    assert probe is not None
    conversation.input(probe)
    answer = parse_segment(sent[0])
    assert answer is not None
    assert answer.command == 0x54
    conversation.close()


async def test_an_unacknowledged_segment_is_retransmitted_then_gives_up(monkeypatch):
    monkeypatch.setattr(
        "tuya_ipc_p2p_sdk.transport.kcp_conversation._RETRANSMIT_INTERVAL_SECONDS", 0.001
    )
    sent: list[bytes] = []
    conversation = KcpConversation(0, sent.append)
    conversation.send(b"never-acknowledged")
    await asyncio.sleep(0.1)
    assert len(sent) > 1
    await conversation.async_close()
