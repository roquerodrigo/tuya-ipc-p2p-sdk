"""An aiomqtt stand-in that records publishes and replays inbound payloads."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace


class FakeMqttError(Exception):
    """Stands in for ``aiomqtt.MqttError``."""


class FakeMessage:
    """One inbound message, shaped like aiomqtt's."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload


class FakeMqttClient:
    """Records what the signaling client sends and hands back what the test queues."""

    instances: list[FakeMqttClient] = []
    fail_on_connect = False
    fail_on_publish = False

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.published: list[tuple[str, bytes]] = []
        self.subscribed: list[str] = []
        self.inbound: asyncio.Queue[bytes] = asyncio.Queue()
        self.closed = False
        FakeMqttClient.instances.append(self)

    async def __aenter__(self) -> FakeMqttClient:
        if FakeMqttClient.fail_on_connect:
            raise FakeMqttError("refused")
        return self

    async def __aexit__(self, *_args: object) -> None:
        self.closed = True

    async def subscribe(self, topic: str, qos: int = 0) -> None:
        self.subscribed.append(topic)

    async def publish(self, topic: str, payload: bytes, qos: int = 0) -> None:
        if FakeMqttClient.fail_on_publish:
            raise FakeMqttError("not connected")
        self.published.append((topic, payload))

    @property
    def messages(self) -> object:
        return _Messages(self.inbound)

    def deliver(self, payload: bytes) -> None:
        self.inbound.put_nowait(payload)


class _Messages:
    """The async iterator aiomqtt exposes as ``client.messages``."""

    def __init__(self, queue: asyncio.Queue[bytes]) -> None:
        self._queue = queue

    def __aiter__(self) -> _Messages:
        return self

    async def __anext__(self) -> FakeMessage:
        return FakeMessage(await self._queue.get())


def install(monkeypatch, module: str) -> type[FakeMqttClient]:
    """Point one module's ``aiomqtt`` at the fake and reset its state."""
    FakeMqttClient.instances = []
    FakeMqttClient.fail_on_connect = False
    FakeMqttClient.fail_on_publish = False
    monkeypatch.setattr(
        f"{module}.aiomqtt",
        SimpleNamespace(Client=FakeMqttClient, MqttError=FakeMqttError),
    )
    return FakeMqttClient
