import hashlib
import json

import pytest
from cryptography.hazmat.primitives.asymmetric import padding

from conftest import encrypted_envelope, error_envelope
from tuya_ipc_p2p_sdk import MOMCOZY
from tuya_ipc_p2p_sdk.crypto import md5_hex
from tuya_ipc_p2p_sdk.exceptions import (
    TuyaIpcP2pAuthenticationError,
    TuyaIpcP2pGatewayError,
    TuyaIpcP2pProtocolError,
)
from tuya_ipc_p2p_sdk.gateway.body import decrypt_post_data
from tuya_ipc_p2p_sdk.gateway.client import GatewayClient
from tuya_ipc_p2p_sdk.gateway.signing import pre_login_body_key
from tuya_ipc_p2p_sdk.models import AccountSession

ECODE = "0123456789abcdef"
SID = "examplesid0000000000000000000000000000000000000000000000"
ACCOUNT = AccountSession(SID, ECODE, "exampleuid0000000001", "a" * 44)

RTC_CONFIG = {
    "id": "exampledevice000000001",
    "motoId": "signaling3",
    "password": "abcd1234",
    "p2pConfig": {
        "session": {
            "sessionId": "exampledevice0000000011700000000AbCdEfGh",
            "aesKey": "000102030405060708090a0b0c0d0e0f",
            "iceUfrag": "UfRg",
            "icePassword": "zhlW36t6BI2HxURDda1vmcla",
            "traceId": "trace",
        },
        "tcpRelay": {
            "urls": ["tcp4:10.0.0.9:1443"],
            "username": "1700036000:exampledevice000000001",
            "credential": "AAAABBBBCCCCDDDDEEEEFFFFGGGG",
            "sessionId": "exampledevice0000000011700036000ZzYyXxWw",
        },
    },
}


class FakeGateway:
    """Answers whatever the client asks, without a socket."""

    def __init__(self, results: dict[str, object]) -> None:
        self.results = results
        self.calls: list[dict[str, str]] = []
        self.errors: dict[str, tuple[str, str]] = {}

    async def post(self, api: str, params: dict[str, str]) -> str:
        self.calls.append(params)
        ecode = ECODE if "sid" in params else None
        if api in self.errors:
            code, message = self.errors[api]
            return error_envelope(params["requestId"], ecode, code, message)
        return encrypted_envelope(params["requestId"], ecode, self.results[api])


@pytest.fixture
def gateway(monkeypatch):
    fake = FakeGateway({})

    async def fake_post(self, api, params):
        return await fake.post(api, params)

    monkeypatch.setattr(GatewayClient, "_post", fake_post)
    return fake


async def test_a_call_is_signed_and_its_result_decrypted(gateway):
    gateway.results["some.api"] = {"value": 1}
    client = GatewayClient()
    assert await client.async_call("some.api", "1.0", {}, ACCOUNT) == {"value": 1}

    params = gateway.calls[0]
    assert params["a"] == "some.api"
    assert params["et"] == "3"
    assert params["sid"] == SID
    assert len(params["sign"]) == 64


async def test_a_refusal_becomes_a_gateway_error(gateway):
    gateway.errors["some.api"] = ("USER_SESSION_INVALID", "session gone")
    client = GatewayClient()
    with pytest.raises(TuyaIpcP2pGatewayError) as raised:
        await client.async_call("some.api", "1.0", {}, ACCOUNT)
    assert raised.value.session_expired is True
    assert raised.value.code == "USER_SESSION_INVALID"


async def test_an_unrelated_refusal_does_not_ask_for_a_new_login(gateway):
    gateway.errors["some.api"] = ("DEVICE_OFFLINE", "not reachable")
    client = GatewayClient()
    with pytest.raises(TuyaIpcP2pGatewayError) as raised:
        await client.async_call("some.api", "1.0", {}, ACCOUNT)
    assert raised.value.session_expired is False


async def test_a_response_that_is_not_json_is_rejected(monkeypatch):
    async def fake_post(self, api, params):
        return "<html>gateway down</html>"

    monkeypatch.setattr(GatewayClient, "_post", fake_post)
    with pytest.raises(TuyaIpcP2pProtocolError):
        await GatewayClient().async_call("some.api", "1.0", {})


async def test_an_empty_result_is_rejected(monkeypatch):
    async def fake_post(self, api, params):
        return json.dumps({"success": True})

    monkeypatch.setattr(GatewayClient, "_post", fake_post)
    with pytest.raises(TuyaIpcP2pProtocolError, match="empty result"):
        await GatewayClient().async_call("some.api", "1.0", {})


async def test_login_encrypts_the_password_under_the_key_the_gateway_hands_out(
    gateway, login_key_pair
):
    _private, modulus, exponent = login_key_pair
    gateway.results["smartlife.m.user.username.token.get"] = {
        "publicKey": modulus,
        "exponent": exponent,
        "token": "login-token",
    }
    gateway.results["smartlife.m.user.email.password.login"] = {
        "sid": SID,
        "ecode": ECODE,
        "uid": "exampleuid0000000001",
    }
    account = await GatewayClient().async_login("user@example.com", "hunter2", "55")
    assert account.uid == "exampleuid0000000001"
    assert account.device_fingerprint == "a" * 44

    login_call = gateway.calls[1]
    assert "sid" not in login_call
    assert len(login_call["postData"]) > 0


async def test_login_failure_becomes_an_authentication_error(gateway):
    gateway.errors["smartlife.m.user.username.token.get"] = ("USER_PASSWD_WRONG", "no")
    with pytest.raises(TuyaIpcP2pAuthenticationError):
        await GatewayClient().async_login("user@example.com", "wrong", "55")


async def test_uid_login_uses_the_oem_token_and_returns_a_session(gateway, login_key_pair):
    private, modulus, exponent = login_key_pair
    gateway.results["thing.m.user.username.token.get"] = {
        "publicKey": modulus,
        "exponent": exponent,
        "token": "login-token",
    }
    gateway.results["thing.m.user.uid.password.login.reg"] = {
        "sid": SID,
        "ecode": ECODE,
        "uid": "oem-uid",
    }
    account = await GatewayClient().async_login_uid("49", "oem-uid", "delegated-token")
    assert account.uid == "oem-uid"
    assert len(gateway.calls) == 2

    token_call, login_call = gateway.calls
    token_post = json.loads(
        decrypt_post_data(pre_login_body_key(token_call["requestId"]), token_call["postData"])
    )
    assert token_call["a"] == "thing.m.user.username.token.get"
    assert token_call["v"] == "2.0"
    assert token_post == {
        "countryCode": "49",
        "username": "oem-uid",
        "isUid": True,
    }

    login_post = json.loads(
        decrypt_post_data(pre_login_body_key(login_call["requestId"]), login_call["postData"])
    )
    decrypted_password = private.decrypt(
        bytes.fromhex(login_post["passwd"]), padding.PKCS1v15()
    ).decode()
    assert login_call["a"] == "thing.m.user.uid.password.login.reg"
    assert login_call["v"] == "1.0"
    assert (
        decrypted_password
        == hashlib.md5(  # noqa: S324 -- protocol requirement
            b"delegated-token"
        ).hexdigest()
    )
    assert login_post == {
        "countryCode": "49",
        "uid": "oem-uid",
        "passwd": login_post["passwd"],
        "token": "login-token",
        "ifencrypt": 1,
        "createGroup": False,
        "options": '{"group": 1}',
    }


async def test_uid_login_works_when_md5_is_blocked_for_security(
    gateway, login_key_pair, monkeypatch
):
    _private, modulus, exponent = login_key_pair
    gateway.results["thing.m.user.username.token.get"] = {
        "publicKey": modulus,
        "exponent": exponent,
        "token": "login-token",
    }
    gateway.results["thing.m.user.uid.password.login.reg"] = {
        "sid": SID,
        "ecode": ECODE,
        "uid": "oem-uid",
    }
    real_md5 = hashlib.md5

    def fips_md5(value=b"", *, usedforsecurity=True):
        if usedforsecurity:
            raise ValueError("MD5 blocked for security use")
        return real_md5(value, usedforsecurity=False)

    monkeypatch.setattr(hashlib, "md5", fips_md5)
    account = await GatewayClient().async_login_uid("49", "oem-uid", "delegated-token")
    assert account.uid == "oem-uid"


async def test_momcozy_profile_drives_gateway_signing_and_mqtt_identity(monkeypatch):
    calls = []

    async def fake_post(self, api, params):
        calls.append(params)
        return encrypted_envelope(params["requestId"], None, {"value": 1}, MOMCOZY.composite_key)

    monkeypatch.setattr(GatewayClient, "_post", fake_post)
    client = GatewayClient("eu", profile=MOMCOZY)
    assert await client.async_call("some.api", "1.0", {"hello": "world"}) == {"value": 1}

    params = calls[0]
    assert params["clientId"] == MOMCOZY.client_id
    assert params["chKey"] == MOMCOZY.ch_key
    assert params["ttid"] == "android"
    assert params["deviceCoreVersion"] == "7.5.0"
    assert json.loads(
        decrypt_post_data(
            pre_login_body_key(params["requestId"], MOMCOZY.composite_key),
            params["postData"],
        )
    ) == {"hello": "world"}

    identity = client.mqtt_identity(ACCOUNT)
    assert identity.host == "m1.tuyaeu.com"
    assert identity.client_id.startswith("com.lute.momcozy_mb_")
    assert f"_{MOMCOZY.client_id}_{MOMCOZY.ch_key}_mb_" in identity.username


def test_momcozy_request_signature_matches_the_fixed_protocol_vector(monkeypatch):
    monkeypatch.setattr("tuya_ipc_p2p_sdk.gateway.client.time.time", lambda: 1_700_000_000)
    params = GatewayClient("eu", profile=MOMCOZY)._build_params(
        "some.api",
        "1.0",
        "fixed-request-id",
        "encrypted-body",
        None,
        None,
    )
    assert params["sign"] == ("b03e367c7513417eb9b45578a1b1b87fff611a22436c457a968ec69fc8958d9c")


async def test_the_encrypted_password_decrypts_to_the_md5_of_the_plaintext(gateway, login_key_pair):
    from tuya_ipc_p2p_sdk.gateway.client import _encrypt_password

    private, modulus, exponent = login_key_pair
    encrypted = _encrypt_password(modulus, exponent, md5_hex("hunter2"))
    assert private.decrypt(bytes.fromhex(encrypted), padding.PKCS1v15()).decode() == md5_hex(
        "hunter2"
    )


async def test_the_stream_config_is_parsed_into_a_typed_record(gateway):
    gateway.results["m.ipc.v4.rtc.config.get"] = RTC_CONFIG
    config = await GatewayClient().async_stream_config(
        ACCOUNT, "exampledevice000000001", "0123456789abcdef"
    )
    assert config.device_password == "abcd1234"
    assert config.relay_token.endpoint == ("10.0.0.9", 1443)


async def test_device_listing_walks_every_home_and_skips_incomplete_entries(gateway):
    gateway.results["tuya.m.location.list"] = [{"gid": 1, "name": "Home"}, {"name": "no gid"}]
    gateway.results["tuya.m.my.group.device.list"] = [
        {
            "devId": "exampledevice000000001",
            "name": "Feeder",
            "category": "cwwsq",
            "localKey": "0123456789abcdef",
            "isOnline": True,
        },
        {"devId": "no-local-key"},
    ]
    devices = await GatewayClient().async_list_devices(ACCOUNT)
    assert [device.device_id for device in devices] == ["exampledevice000000001"]
    assert devices[0].name == "Feeder"
    assert devices[0].online is True


async def test_discovery_keeps_only_the_devices_that_answer_the_ipc_config(gateway):
    gateway.results["tuya.m.location.list"] = [{"gid": 1}]
    gateway.results["tuya.m.my.group.device.list"] = [
        {"devId": "camera", "name": "Camera", "localKey": "0123456789abcdef"},
        {"devId": "plug", "name": "Plug", "localKey": "fedcba9876543210"},
    ]
    gateway.results["m.ipc.v4.rtc.config.get"] = RTC_CONFIG
    gateway.errors = {}

    calls: list[str] = []
    original = GatewayClient.async_stream_config

    async def only_the_camera(self, session, device_id, local_key):
        calls.append(device_id)
        if device_id != "camera":
            raise TuyaIpcP2pGatewayError("m.ipc.v4.rtc.config.get", "NOT_IPC", "no")
        return await original(self, session, device_id, local_key)

    GatewayClient.async_stream_config = only_the_camera
    try:
        cameras = await GatewayClient().async_discover_cameras(ACCOUNT)
    finally:
        GatewayClient.async_stream_config = original
    assert [camera.device_id for camera in cameras] == ["camera"]
    assert calls == ["camera", "plug"]


async def test_a_result_of_the_wrong_shape_is_rejected(gateway):
    gateway.results["tuya.m.location.list"] = {"not": "a list"}
    with pytest.raises(TuyaIpcP2pProtocolError, match="not a list"):
        await GatewayClient().async_list_devices(ACCOUNT)


async def test_the_mqtt_identity_follows_the_client_region(gateway):
    assert GatewayClient("eu").mqtt_identity(ACCOUNT).host == "m1-eu.lifeaiot.com"


async def test_closing_a_client_that_owns_no_session_is_harmless():
    client = GatewayClient()
    await client.async_close()
    async with GatewayClient() as scoped:
        assert scoped is not None
