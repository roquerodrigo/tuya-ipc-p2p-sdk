"""Tuya mobile-app identities supported by the gateway client."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


@dataclass(frozen=True, slots=True)
class AppProfile:
    """Public client constants and routing needed for app interoperability."""

    name: str
    package_name: str
    certificate_sha256: str
    derived_key: str
    app_secret: str
    client_id: str
    ch_key: str
    app_version: str
    sdk_version: str
    ttid: str
    partner_identity: str
    client_id_salt: str
    gateway_hosts: Mapping[str, str]
    broker_hosts: Mapping[str, str]
    default_region: str
    language: str = "en_US"
    request_params: Mapping[str, str] | None = None

    @property
    def composite_key(self) -> str:
        """Return the Tuya request-signing key material."""
        return f"{self.package_name}_{self.certificate_sha256}_{self.derived_key}_{self.app_secret}"

    def gateway_url(self, region: str) -> str:
        """Return the API gateway URL for *region*."""
        try:
            return self.gateway_hosts[region]
        except KeyError as exception:
            raise ValueError(f"Unsupported {self.name} region: {region}") from exception

    def broker_host(self, region: str) -> str:
        """Return the MQTT signaling broker for *region*."""
        try:
            return self.broker_hosts[region]
        except KeyError as exception:
            raise ValueError(f"Unsupported {self.name} region: {region}") from exception


SMART_LIFE = AppProfile(
    name="Smart Life",
    package_name="com.tuya.smartlife",
    certificate_sha256=(
        "0F:C3:61:99:9C:C0:C3:5B:A8:AC:A5:7D:AA:55:93:A2:"
        "0C:F5:57:27:70:2E:A8:5A:D7:B3:22:89:49:F8:88:FE"
    ),
    derived_key="jfg5rs5kkmrj5mxahugvucrsvw43t48x",
    app_secret="r3me7ghmxjevrvnpemwmhw3fxtacphyg",  # noqa: S106 -- protocol constant
    client_id="ekmnwp9f5pnh3trdtpgy",
    ch_key="ec9709a4",
    app_version="7.10.3",
    sdk_version="5.2.0",
    ttid="sdk_international@ekmnwp9f5pnh3trdtpgy",
    partner_identity="p1000018",
    client_id_salt="sdkfasodifca",
    gateway_hosts={
        region: f"https://a1-{region}.lifeaiot.com/api.json"
        for region in ("us", "eu", "cn", "in", "we")
    },
    broker_hosts={region: f"m1-{region}.lifeaiot.com" for region in ("us", "eu", "cn", "in", "we")},
    default_region="us",
)

MOMCOZY = AppProfile(
    name="Momcozy",
    package_name="com.lute.momcozy",
    certificate_sha256=(
        "86:48:51:9D:96:A7:15:C0:3F:27:A1:EF:8A:AC:9E:E2:"
        "B8:2E:83:76:3F:97:E8:8F:2E:45:28:3D:2E:A5:93:F2"
    ),
    derived_key="ker9483upg35v53uqaryum5j3wyhnv3x",
    app_secret="jnmtjkaqcvervwfxeu75kvtnrksgwutp",  # noqa: S106 -- protocol constant
    client_id="4t7ucfdpqkpys9fwy5yv",
    ch_key="39641be9",
    app_version="3.4.0",
    sdk_version="7.5.0",
    ttid="android",
    partner_identity="p1000018",
    client_id_salt="sdkfasodifca",
    gateway_hosts={
        "cn": "https://a1.tuyacn.com/api.json",
        "us": "https://a1-us.iotbing.com/api.json",
        "eu": "https://a1.tuyaeu.com/api.json",
        "in": "https://a1-in.iotbing.com/api.json",
    },
    broker_hosts={
        "cn": "m1.tuyacn.com",
        "us": "m1-us.iotbing.com",
        "eu": "m1.tuyaeu.com",
        "in": "m1-in.iotbing.com",
    },
    default_region="eu",
    request_params={
        "cp": "gzip",
        "deviceCoreVersion": "7.5.0",
        "osSystem": "14",
        "platform": "Android",
        "timeZoneId": "Europe/Berlin",
        "channel": "sdk",
        "bizData": '{"customDomainSupport":"1","sdkInt":"34","brand":"generic"}',
    },
)
