import pytest

from tuya_ipc_p2p_sdk import TuyaIpcP2pClient
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pGatewayError
from tuya_ipc_p2p_sdk.models import AccountSession, TuyaDevice

ACCOUNT = AccountSession("sid", "ecode", "uid", "a" * 44)
CAMERA = TuyaDevice("exampledevice000000001", "Feeder", "cwwsq", "0123456789abcdef")


class FakeGateway:
    """Counts the calls the client makes and can refuse them once."""

    def __init__(self) -> None:
        self.logins = 0
        self.configs = 0
        self.devices = 0
        self.expire_once = False

    async def async_login(self, email, password, country_code):
        self.logins += 1
        return ACCOUNT

    def _maybe_expire(self) -> None:
        if self.expire_once:
            self.expire_once = False
            raise TuyaIpcP2pGatewayError("api", "USER_SESSION_INVALID", "session gone")

    async def async_stream_config(self, session, device_id, local_key):
        self._maybe_expire()
        self.configs += 1
        return {"device_id": device_id}

    async def async_list_devices(self, session):
        self._maybe_expire()
        self.devices += 1
        return [CAMERA]

    async def async_discover_cameras(self, session):
        self._maybe_expire()
        return [CAMERA]

    def mqtt_identity(self, session):
        return "identity"

    async def async_close(self) -> None:
        return None


@pytest.fixture
def client(monkeypatch):
    gateway = FakeGateway()
    monkeypatch.setattr("tuya_ipc_p2p_sdk.client.GatewayClient", lambda *args, **kwargs: gateway)
    built = TuyaIpcP2pClient("user@example.com", "hunter2", "55")
    return built, gateway


async def test_the_first_call_logs_in_and_later_ones_reuse_the_session(client):
    built, gateway = client
    assert await built.async_uid() == "uid"
    assert await built.async_mqtt_identity() == "identity"
    await built.async_list_devices()
    assert gateway.logins == 1


async def test_a_rejected_session_is_renewed_once(client):
    built, gateway = client
    await built.async_account()
    gateway.expire_once = True
    await built.async_stream_config("exampledevice000000001", "0123456789abcdef")
    assert gateway.logins == 2
    assert gateway.configs == 1


async def test_a_rejected_session_is_renewed_for_listing_too(client):
    built, gateway = client
    await built.async_account()
    gateway.expire_once = True
    assert await built.async_list_devices() == [CAMERA]
    assert gateway.logins == 2


async def test_an_unrelated_refusal_is_raised_as_it_is(client, monkeypatch):
    built, gateway = client

    async def always_refuse(session, device_id, local_key):
        raise TuyaIpcP2pGatewayError("api", "DEVICE_OFFLINE", "not reachable")

    gateway.async_stream_config = always_refuse
    with pytest.raises(TuyaIpcP2pGatewayError):
        await built.async_stream_config("device", "key")


async def test_discovery_is_exposed_through_the_client(client):
    built, _gateway = client
    assert await built.async_discover_cameras() == [CAMERA]


async def test_logging_in_again_replaces_the_session(client):
    built, gateway = client
    await built.async_login()
    await built.async_login()
    assert gateway.logins == 2


async def test_a_stream_is_built_without_connecting_anything(client):
    built, _gateway = client
    stream = built.create_camera_stream("exampledevice000000001", "0123456789abcdef")
    assert stream.device_id == "exampledevice000000001"
    assert stream.running is False


async def test_the_client_is_a_context_manager(client):
    built, _gateway = client
    async with built as scoped:
        assert scoped is built
