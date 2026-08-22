import json

import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from tuya_ipc_p2p_sdk.gateway.body import encrypt_post_data
from tuya_ipc_p2p_sdk.gateway.signing import body_key, pre_login_body_key
from tuya_ipc_p2p_sdk.json_types import dump_json


@pytest.fixture(scope="session")
def login_key_pair():
    """An RSA key pair standing in for the one the token call hands out."""
    private = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    numbers = private.public_key().public_numbers()
    return private, str(numbers.n), str(numbers.e)


def encrypted_envelope(request_id: str, ecode: str | None, result: object) -> str:
    """Wrap a result the way the gateway does, encrypted under the request's body key."""
    key = body_key(request_id, ecode) if ecode else pre_login_body_key(request_id)
    inner = dump_json({"result": result, "success": True})
    return json.dumps({"result": encrypt_post_data(key, inner)})


def error_envelope(request_id: str, ecode: str | None, code: str, message: str) -> str:
    """Wrap a refusal the way the gateway does."""
    key = body_key(request_id, ecode) if ecode else pre_login_body_key(request_id)
    inner = dump_json({"errorCode": code, "errorMsg": message, "success": False})
    return json.dumps({"result": encrypt_post_data(key, inner)})
