import pytest

from tuya_ipc_p2p_sdk.exceptions import TuyaIpcP2pProtocolError
from tuya_ipc_p2p_sdk.json_types import (
    dump_json,
    object_list,
    optional_int,
    optional_object,
    optional_str,
    parse_json_object,
    require_object,
    require_str,
    str_list,
)

SOURCE = {
    "name": "camera",
    "empty": "",
    "count": 3,
    "flag": True,
    "nested": {"inner": "value"},
    "items": [{"a": 1}, "skip", {"b": 2}],
    "urls": ["tcp4:1.2.3.4:1443", 7],
    "wrong": 5,
}


def test_parse_json_object_rejects_anything_but_an_object():
    assert parse_json_object('{"a":1}') == {"a": 1}
    with pytest.raises(TuyaIpcP2pProtocolError):
        parse_json_object("[1,2]")
    with pytest.raises(TuyaIpcP2pProtocolError):
        parse_json_object("not json")


def test_dump_json_has_no_whitespace_padding():
    assert dump_json({"a": 1, "b": [2, 3]}) == b'{"a":1,"b":[2,3]}'


def test_string_accessors():
    assert optional_str(SOURCE, "name") == "camera"
    assert optional_str(SOURCE, "empty") is None
    assert optional_str(SOURCE, "missing") is None
    assert require_str(SOURCE, "name") == "camera"
    with pytest.raises(TuyaIpcP2pProtocolError):
        require_str(SOURCE, "empty")


def test_integer_accessor_does_not_accept_booleans():
    assert optional_int(SOURCE, "count") == 3
    assert optional_int(SOURCE, "flag") is None
    assert optional_int(SOURCE, "name") is None


def test_object_accessors():
    assert optional_object(SOURCE, "nested") == {"inner": "value"}
    assert optional_object(SOURCE, "wrong") is None
    assert require_object(SOURCE, "nested") == {"inner": "value"}
    with pytest.raises(TuyaIpcP2pProtocolError):
        require_object(SOURCE, "wrong")


def test_list_accessors_skip_entries_of_another_shape():
    assert object_list(SOURCE, "items") == [{"a": 1}, {"b": 2}]
    assert object_list(SOURCE, "wrong") == []
    assert str_list(SOURCE, "urls") == ["tcp4:1.2.3.4:1443"]
    assert str_list(SOURCE, "wrong") == []
