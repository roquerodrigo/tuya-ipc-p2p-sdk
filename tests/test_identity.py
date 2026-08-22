import pytest

from tuya_ipc_p2p_sdk.gateway.identity import (
    build_mqtt_identity,
    mqtt_client_id,
    mqtt_password,
    mqtt_username,
)
from tuya_ipc_p2p_sdk.models import AccountSession

SID = "examplesid0000000000000000000000000000000000000000000000"


def test_signaling_mqtt_username():
    assert mqtt_username(SID, "0123456789abcdef") == (
        f"p1000018_v1_ekmnwp9f5pnh3trdtpgy_ec9709a4_mb_{SID}032f4795fcd4c696"
    )


def test_signaling_mqtt_client_id():
    assert mqtt_client_id("a" * 44, "exampleuid0000000001") == (
        "com.tuya.smartlife_mb_" + "a" * 44 + "_ae2f30de960ccbbdd22a3c28e134508d_DEFAULT"
    )


@pytest.mark.parametrize(
    ("ecode", "want"),
    [
        ("0123456789abcdef", "8126b6b6b18cfc39"),
        ("test1234abcd", "e5b866db21460e11"),
        ("aaaaaaaaaaaaaaaa", "2c1f3b22c9bf38ce"),
        ("", "ca0eb0ec40a52637"),
    ],
)
def test_signaling_mqtt_password_vectors(ecode, want):
    assert mqtt_password(ecode) == want


def test_identity_points_at_the_regional_broker():
    account = AccountSession(SID, "0123456789abcdef", "exampleuid0000000001", "a" * 44)
    identity = build_mqtt_identity(account, "eu")
    assert identity.host == "m1-eu.lifeaiot.com"
    assert identity.port == 8883
    assert identity.client_id.endswith("_DEFAULT")
    assert identity.username.startswith("p1000018_v1_")
