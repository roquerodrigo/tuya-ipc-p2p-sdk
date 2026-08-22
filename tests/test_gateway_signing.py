import pytest

from tuya_ipc_p2p_sdk.const import COMPOSITE_KEY
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.gateway.body import decrypt_post_data, encrypt_post_data
from tuya_ipc_p2p_sdk.gateway.signing import (
    body_key,
    build_sign_string,
    post_data_sign_field,
    pre_login_body_key,
    sign,
    swap_sign_string,
)

# The vectors use placeholder identities; they pin the algorithm and the composite
# key, so any drift in either breaks the test. They match the Go client's vectors.
SIGN_VECTORS = [
    (
        "a=m.ipc.v4.rtc.config.get||appVersion=7.10.3||chKey=ec9709a4"
        "||clientId=ekmnwp9f5pnh3trdtpgy"
        "||deviceId=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa||et=3||lang=en_US"
        "||os=Android||postData=0123456789abcdef0123456789abcdef"
        "||requestId=00000000-0000-4000-8000-000000000001"
        "||sid=examplesid0000000000000000000000000000000000000000000000"
        "||time=1700000000||ttid=sdk_international@ekmnwp9f5pnh3trdtpgy||v=1.0",
        "279d01df9848c30c6ec924ebaaafa307574bb4eb89d821d860105db6ccb816da",
    ),
    (
        "a=smartlife.m.user.email.password.login||appVersion=7.10.3||chKey=ec9709a4"
        "||clientId=ekmnwp9f5pnh3trdtpgy"
        "||deviceId=aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa||et=3||lang=en_US"
        "||os=Android||postData=fedcba9876543210fedcba9876543210"
        "||requestId=00000000-0000-4000-8000-000000000002"
        "||time=1700000001||ttid=sdk_international@ekmnwp9f5pnh3trdtpgy||v=3.0",
        "3ab767a519195344ef88b2734cf6473c4b4d1f00428d83672cac3307b9b888bd",
    ),
]


@pytest.mark.parametrize(("sign_string", "want"), SIGN_VECTORS)
def test_sign_vectors(sign_string, want):
    assert sign(sign_string) == want


def test_build_sign_string_rebuilds_the_exact_string():
    sign_string = SIGN_VECTORS[0][0].replace("||postData=0123456789abcdef0123456789abcdef", "")
    params = dict(pair.split("=", 1) for pair in sign_string.split("||"))
    assert build_sign_string(params) == sign_string


def test_build_sign_string_drops_non_whitelisted_and_empty_params():
    got = build_sign_string(
        {"a": "api", "v": "1.0", "sign": "must-not-appear", "nonce": "no", "empty": ""}
    )
    assert got == "a=api||v=1.0"


def test_swap_sign_string():
    assert (
        swap_sign_string("0123456789abcdef0123456789abcdef") == "89abcdef0123456789abcdef01234567"
    )
    assert swap_sign_string("short") == "short"


def test_post_data_sign_field_is_md5_shaped():
    assert len(post_data_sign_field("cGF5bG9hZA==")) == 32


@pytest.mark.parametrize(
    ("request_id", "ecode", "want"),
    [
        ("00000000-0000-4000-8000-000000000001", "0123456789abcdef", "c1dca02963d354db"),
        ("11111111-1111-4111-8111-111111111111", "0123456789abcdef", "8e8768a465b00caf"),
    ],
)
def test_body_key_vectors(request_id, ecode, want):
    assert body_key(request_id, ecode) == want


def test_pre_login_body_key_differs_from_the_session_scoped_one():
    request_id = "00000000-0000-4000-8000-000000000001"
    assert pre_login_body_key(request_id) != body_key(request_id, "0123456789abcdef")
    assert len(pre_login_body_key(request_id)) == 16


def test_composite_key_is_the_four_client_constants():
    assert len(COMPOSITE_KEY.split("_")) == 4
    assert COMPOSITE_KEY.startswith("com.tuya.smartlife_")


def test_post_data_round_trips_and_rejects_the_wrong_key():
    key = "0123456789abcdef"
    plain = b'{"devId":"exampledevice000000001"}'
    encrypted = encrypt_post_data(key, plain)
    assert decrypt_post_data(key, encrypted) == plain
    with pytest.raises(TuyaIpcP2pProtocolError):
        decrypt_post_data("0123456789abcdeX", encrypted)


def test_post_data_rejects_a_body_that_is_not_base64_or_is_too_short():
    with pytest.raises(TuyaIpcP2pProtocolError):
        decrypt_post_data("0123456789abcdef", "not base64!")
    with pytest.raises(TuyaIpcP2pProtocolError):
        decrypt_post_data("0123456789abcdef", "AAAA")
