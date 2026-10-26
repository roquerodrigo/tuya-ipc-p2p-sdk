"""The signaling MQTT identity, derived from the login session."""

from __future__ import annotations

from ..app_profile import SMART_LIFE, AppProfile
from ..const import BROKER_PORT
from ..crypto import md5_hex
from ..models import AccountSession, MqttIdentity


def mqtt_client_id(device_fingerprint: str, uid: str, profile: AppProfile = SMART_LIFE) -> str:
    """Return ``<packageName>_mb_<installId>_<md5(uid + salt)>_DEFAULT``."""
    return (
        f"{profile.package_name}_mb_{device_fingerprint}_"
        f"{md5_hex(uid + profile.client_id_salt)}_DEFAULT"
    )


def mqtt_username(
    sid: str, ecode: str, app_key: str | None = None, profile: AppProfile = SMART_LIFE
) -> str:
    """Return ``p1000018_v1_<appKey>_<chKey>_mb_<sid>`` plus the ecode-bound tail."""
    key = app_key or profile.client_id
    tail = md5_hex(md5_hex(key) + ecode)[16:32]
    return f"{profile.partner_identity}_v1_{key}_{profile.ch_key}_mb_{sid}{tail}"


def mqtt_password(ecode: str, key: str | None = None, profile: AppProfile = SMART_LIFE) -> str:
    """
    Return ``md5(md5(K) + ecode)[8:24]``.

    The slice is used verbatim as the password string; it is not the hex of a
    byte sequence the broker decodes.
    """
    return md5_hex(md5_hex(key or profile.composite_key) + ecode)[8:24]


def build_mqtt_identity(
    session: AccountSession, region: str, profile: AppProfile = SMART_LIFE
) -> MqttIdentity:
    """Assemble the broker identity of one logged-in account."""
    return MqttIdentity(
        host=profile.broker_host(region),
        port=BROKER_PORT,
        client_id=mqtt_client_id(session.device_fingerprint, session.uid, profile),
        username=mqtt_username(session.sid, session.ecode, profile=profile),
        password=mqtt_password(session.ecode, profile=profile),
    )
