import pytest

from tuya_ipc_p2p_sdk.crypto import (
    aes_cbc_decrypt,
    aes_cbc_encrypt,
    aes_ecb_decrypt,
    aes_ecb_encrypt,
    decrypt_record,
    encrypt_record,
    hmac_sha256_hex,
    md5_hex,
    pad_pkcs7,
    random_alphanumeric,
    unpad_pkcs7,
)
from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError

KEY = b"0123456789abcdef"
IV = bytes(range(16))


def test_md5_and_hmac_are_the_documented_digests():
    assert md5_hex("abc") == "900150983cd24fb0d6963f7d28e17f72"
    assert md5_hex(b"abc") == md5_hex("abc")
    assert len(hmac_sha256_hex("key", "message")) == 64


@pytest.mark.parametrize("length", [0, 1, 15, 16, 17, 100])
def test_pkcs7_round_trips_and_always_pads(length):
    plain = b"x" * length
    padded = pad_pkcs7(plain)
    assert len(padded) > length
    assert len(padded) % 16 == 0
    assert unpad_pkcs7(padded) == plain


@pytest.mark.parametrize("padded", [b"", b"x" * 16, bytes(15) + bytes([17])])
def test_unpad_rejects_bad_padding(padded):
    with pytest.raises(TuyaIpcP2pProtocolError):
        unpad_pkcs7(padded)


def test_cbc_round_trips():
    assert aes_cbc_decrypt(KEY, IV, aes_cbc_encrypt(KEY, IV, b"payload")) == b"payload"


def test_cbc_rejects_a_misaligned_ciphertext():
    with pytest.raises(TuyaIpcP2pProtocolError):
        aes_cbc_decrypt(KEY, IV, b"short")


def test_ecb_round_trips():
    assert aes_ecb_decrypt(KEY, aes_ecb_encrypt(KEY, b"signaling body")) == b"signaling body"


def test_ecb_rejects_a_misaligned_ciphertext():
    with pytest.raises(TuyaIpcP2pProtocolError):
        aes_ecb_decrypt(KEY, b"short")


def test_a_record_carries_its_own_iv():
    record = encrypt_record(KEY, b"channel packet")
    assert len(record) % 16 == 0
    assert decrypt_record(KEY, record) == b"channel packet"
    assert encrypt_record(KEY, b"channel packet") != record


def test_record_helpers_reject_a_key_that_is_not_aes_128():
    with pytest.raises(TuyaIpcP2pProtocolError):
        encrypt_record(b"short", b"packet")
    with pytest.raises(TuyaIpcP2pProtocolError):
        decrypt_record(KEY, b"too-short")


def test_random_alphanumeric_has_the_requested_shape():
    value = random_alphanumeric(32)
    assert len(value) == 32
    assert value.isalnum()
