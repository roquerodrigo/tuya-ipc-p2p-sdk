import pytest

from tuya_ipc_p2p_sdk import MOMCOZY
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.momcozy import MomcozyCloudClient, hash_momcozy_password


def test_momcozy_profile_uses_the_apk_identity_and_eu_routing():
    assert MOMCOZY.client_id == "4t7ucfdpqkpys9fwy5yv"
    assert MOMCOZY.ch_key == "39641be9"
    assert MOMCOZY.gateway_url("eu") == "https://a1.tuyaeu.com/api.json"
    assert MOMCOZY.broker_host("eu") == "m1.tuyaeu.com"
    assert MOMCOZY.composite_key.startswith("com.lute.momcozy_86:48:51:9D")


def test_momcozy_password_transform_matches_a_fixed_vector():
    assert hash_momcozy_password("hunter2") == ("5ldPjdmJS8a8T/f/vAgISOs9a9ZHUMr/QBCgP3RZtn8=")


async def test_momcozy_delegation_uses_the_app_login_flow(monkeypatch):
    client = MomcozyCloudClient("de")
    calls = []

    async def fake_json(method, path, **kwargs):
        calls.append((method, path, kwargs))
        if path.endswith("/login/v3"):
            return {"token": "bearer-token"}
        return {"region": "33", "uid": "oem-uid", "token": "delegated-token"}

    monkeypatch.setattr(client, "_json", fake_json)
    credentials = await client.async_tuya_credentials("user@example.com", "hunter2")

    assert credentials.country_code == "33"
    assert credentials.uid == "oem-uid"
    assert credentials.token == "delegated-token"
    assert "delegated-token" not in repr(credentials)
    assert calls[0][0:2] == ("POST", "/api/app/user/login/v3")
    assert calls[0][2]["json"] == {
        "type": 1,
        "email": "user@example.com",
        "password": hash_momcozy_password("hunter2"),
        "platForm": "BREAST_PUMP",
        "remember": 0,
    }
    assert calls[1][0:2] == ("GET", "/api/app/third/tuya/user")
    assert calls[1][2]["headers"]["Authorization"] == "Bearer bearer-token"


async def test_momcozy_rejects_a_malformed_json_response():
    class Response:
        def raise_for_status(self):
            return None

        async def json(self):
            raise ValueError("malformed JSON")

    class Session:
        async def request(self, *args, **kwargs):
            return Response()

    client = MomcozyCloudClient("de", session=Session())
    with pytest.raises(TuyaIpcP2pProtocolError, match="Failed to decode Momcozy response"):
        await client._json("GET", "/test", headers={})
