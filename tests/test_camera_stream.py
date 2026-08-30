import asyncio

import pytest

from tuya_ipc_p2p_sdk.camera_stream import CameraStream
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pDeviceBusyError, TuyaIpcP2pSessionError
from tuya_ipc_p2p_sdk.models import MqttIdentity

IDENTITY = MqttIdentity("m1-us.lifeaiot.com", 8883, "client-id", "username", "password")


class FakeStreamSession:
    """Stands in for a real session; the test drives its frames and its ending."""

    instances: list["FakeStreamSession"] = []
    fail_on_start = 0
    refuse_as_busy = False

    def __init__(self, config, identity, uid, on_frame):
        self.config = config
        self.identity = identity
        self.uid = uid
        self.on_frame = on_frame
        self.frame_count = 0
        self.closed = False
        self._ended: asyncio.Future[str] = asyncio.get_running_loop().create_future()
        FakeStreamSession.instances.append(self)

    async def async_start(self):
        if FakeStreamSession.fail_on_start > 0:
            FakeStreamSession.fail_on_start -= 1
            if FakeStreamSession.refuse_as_busy:
                raise TuyaIpcP2pDeviceBusyError("the device refused it (close_reason=12)")
            raise TuyaIpcP2pSessionError("the device refused it")

    def emit(self, frame: bytes) -> None:
        self.frame_count += 1
        self.on_frame(frame)

    async def async_wait_closed(self) -> str:
        return await asyncio.shield(self._ended)

    async def async_close(self) -> None:
        self.closed = True
        if not self._ended.done():
            self._ended.set_result("closed")


class FakeClient:
    """The parts of the SDK client a stream depends on."""

    def __init__(self) -> None:
        self.configs = 0

    async def async_stream_config(self, device_id: str, local_key: str) -> object:
        self.configs += 1
        return {"device_id": device_id, "local_key": local_key}

    async def async_mqtt_identity(self) -> MqttIdentity:
        return IDENTITY

    async def async_uid(self) -> str:
        return "exampleuid0000000001"


@pytest.fixture
def sessions(monkeypatch):
    FakeStreamSession.instances = []
    FakeStreamSession.fail_on_start = 0
    FakeStreamSession.refuse_as_busy = False
    monkeypatch.setattr("tuya_ipc_p2p_sdk.camera_stream.StreamSession", FakeStreamSession)
    return FakeStreamSession


async def wait_for(predicate, timeout: float = 3.0) -> None:
    async with asyncio.timeout(timeout):
        while not predicate():
            await asyncio.sleep(0.01)


def build_stream(**kwargs) -> CameraStream:
    return CameraStream(FakeClient(), "exampledevice000000001", "0123456789abcdef", **kwargs)


async def test_starting_brings_a_session_up_and_publishes_its_frames(sessions):
    stream = build_stream()
    listener_calls: list[int] = []
    stream.add_state_listener(lambda: listener_calls.append(1))
    await stream.async_start()
    await wait_for(lambda: sessions.instances)

    assert stream.running is True
    assert stream.last_frame is None
    assert stream.streaming is False

    sessions.instances[0].emit(b"\xff\xd8frame-one")
    assert stream.last_frame == b"\xff\xd8frame-one"
    assert stream.streaming is True
    assert listener_calls

    await stream.async_stop()
    assert stream.running is False
    assert sessions.instances[0].closed is True


async def test_subscribers_receive_the_last_frame_and_the_next_ones(sessions):
    stream = build_stream()
    await stream.async_start()
    await wait_for(lambda: sessions.instances)
    sessions.instances[0].emit(b"first")

    frames: list[bytes] = []

    async def consume() -> None:
        async for frame in stream.async_frames():
            frames.append(frame)
            if len(frames) == 3:
                return

    consumer = asyncio.create_task(consume())
    await wait_for(lambda: stream.viewer_count == 1)
    sessions.instances[0].emit(b"second")
    sessions.instances[0].emit(b"third")
    await asyncio.wait_for(consumer, 3)
    assert frames == [b"first", b"second", b"third"]
    await stream.async_close()


async def test_a_slow_consumer_skips_ahead_rather_than_falling_behind(sessions):
    stream = build_stream()
    await stream.async_start()
    await wait_for(lambda: sessions.instances)

    sessions.instances[0].emit(b"seed")
    iterator = stream.async_frames()
    assert await anext(iterator) == b"seed"
    for index in range(10):
        sessions.instances[0].emit(f"frame-{index}".encode())
    assert stream.viewer_count == 1
    assert await anext(iterator) == b"frame-8"
    await iterator.aclose()
    await stream.async_close()


async def test_waiting_for_a_frame_returns_the_one_that_arrives(sessions):
    stream = build_stream()
    await stream.async_start()
    await wait_for(lambda: sessions.instances)

    async def emit_soon() -> None:
        await asyncio.sleep(0.05)
        sessions.instances[0].emit(b"late-frame")

    asyncio.create_task(emit_soon())
    assert await stream.async_wait_for_frame(2) == b"late-frame"
    assert await stream.async_wait_for_frame(2) == b"late-frame"
    await stream.async_close()


async def test_waiting_for_a_frame_that_never_comes_gives_up(sessions):
    stream = build_stream()
    await stream.async_start()
    assert await stream.async_wait_for_frame(0.05) is None
    await stream.async_close()


async def test_a_failing_session_is_retried_with_a_fresh_config(sessions):
    sessions.fail_on_start = 2
    stream = build_stream(retry_min_seconds=0.01, session_cooldown_seconds=0.0)
    await stream.async_start()
    await wait_for(lambda: len(sessions.instances) >= 3)
    await stream.async_stop()
    assert len(sessions.instances) >= 3


async def test_a_session_that_ends_is_started_again(sessions):
    stream = build_stream(retry_min_seconds=0.01, session_cooldown_seconds=0.0)
    await stream.async_start()
    await wait_for(lambda: sessions.instances)
    await sessions.instances[0].async_close()
    await wait_for(lambda: len(sessions.instances) >= 2)
    await stream.async_stop()


async def test_a_stalled_session_is_torn_down(sessions, monkeypatch):
    monkeypatch.setattr("tuya_ipc_p2p_sdk.camera_stream._STALL_CHECK_INTERVAL_SECONDS", 0.01)
    stream = build_stream(
        stall_timeout_seconds=0.05, retry_min_seconds=0.01, session_cooldown_seconds=0.0
    )
    await stream.async_start()
    await wait_for(lambda: sessions.instances)
    sessions.instances[0].emit(b"one-frame")
    await wait_for(lambda: sessions.instances[0].closed)
    await stream.async_stop()


async def test_starting_twice_keeps_one_supervisor(sessions):
    stream = build_stream()
    await stream.async_start()
    await stream.async_start()
    await wait_for(lambda: sessions.instances)
    await asyncio.sleep(0.05)
    assert len(sessions.instances) == 1
    await stream.async_stop()
    await stream.async_stop()


async def test_the_local_key_and_the_sensitivity_can_be_rotated(sessions):
    stream = build_stream()
    assert stream.local_key == "0123456789abcdef"
    stream.local_key = "fedcba9876543210"
    assert stream.local_key == "fedcba9876543210"
    assert stream.device_id == "exampledevice000000001"

    stream.set_motion_sensitivity(2)
    assert stream.motion_detected is False


async def test_motion_is_reported_from_the_frames(sessions):
    stream = build_stream(motion_sensitivity=2)
    states: list[bool] = []
    stream.add_state_listener(lambda: states.append(stream.motion_detected))
    await stream.async_start()
    await wait_for(lambda: sessions.instances)

    session = sessions.instances[0]
    for index in range(20):
        session.emit(b"x" * (17850 + (index % 5) * 12 - 24))
    session.emit(b"x" * 23000)
    session.emit(b"x" * 26000)
    assert stream.motion_detected is True
    assert True in states
    await stream.async_close()


async def test_a_listener_that_raises_does_not_stop_the_others(sessions):
    stream = build_stream()
    calls: list[str] = []

    def broken() -> None:
        calls.append("broken")
        raise RuntimeError("listener blew up")

    remove = stream.add_state_listener(broken)
    stream.add_state_listener(lambda: calls.append("healthy"))
    await stream.async_start()
    await wait_for(lambda: sessions.instances)
    sessions.instances[0].emit(b"frame")
    assert "healthy" in calls

    remove()
    remove()
    await stream.async_close()


async def test_a_run_of_busy_replies_reports_a_camera_that_needs_a_power_cycle(sessions):
    """The device stops answering altogether, and only the hardware clears it."""
    sessions.fail_on_start = 3
    sessions.refuse_as_busy = True
    reported: list[bool] = []
    stream = build_stream(
        retry_min_seconds=0.01,
        session_cooldown_seconds=0.0,
        busy_refusal_limit=3,
        refused_retry_seconds=0.01,
    )
    stream.add_state_listener(lambda: reported.append(stream.needs_power_cycle))
    await stream.async_start()
    await wait_for(lambda: stream.needs_power_cycle)
    await stream.async_stop()

    assert True in reported


async def test_a_camera_that_answers_again_stops_needing_a_power_cycle(sessions):
    sessions.fail_on_start = 2
    sessions.refuse_as_busy = True
    stream = build_stream(
        retry_min_seconds=0.01,
        session_cooldown_seconds=0.0,
        busy_refusal_limit=2,
        refused_retry_seconds=0.01,
    )
    await stream.async_start()
    await wait_for(lambda: stream.needs_power_cycle)
    await wait_for(lambda: len(sessions.instances) >= 3)
    sessions.instances[-1].emit(b"\xff\xd8frame")
    await sessions.instances[-1].async_close()
    await wait_for(lambda: not stream.needs_power_cycle)
    await stream.async_stop()

    assert stream.needs_power_cycle is False


async def test_a_refusal_that_is_not_busy_does_not_count_towards_the_limit(sessions):
    sessions.fail_on_start = 4
    stream = build_stream(
        retry_min_seconds=0.01, session_cooldown_seconds=0.0, busy_refusal_limit=2
    )
    await stream.async_start()
    await wait_for(lambda: len(sessions.instances) >= 4)
    await stream.async_stop()

    assert stream.needs_power_cycle is False
