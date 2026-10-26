"""Momcozy account login used to obtain Tuya UID-login credentials."""

from __future__ import annotations

import asyncio
import base64
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Self
from uuid import uuid4
from zoneinfo import ZoneInfo

import aiohttp
from cryptography.hazmat.primitives.kdf.argon2 import Argon2id

from .exceptions import (
    TuyaIpcP2pAuthenticationError,
    TuyaIpcP2pConnectionError,
    TuyaIpcP2pProtocolError,
)

if TYPE_CHECKING:
    from collections.abc import Mapping
    from types import TracebackType

_BASE_URL = "https://app-api.mcozycloud.com"
_PASSWORD_SALT = base64.b64decode("5waV6ARzSxRgap4h")
_TIMEOUT_SECONDS = 20


@dataclass(frozen=True, slots=True)
class _MomcozyTuyaCredentials:
    """Short-lived credentials Momcozy issues for Tuya UID login."""

    country_code: str
    uid: str
    token: str = field(repr=False)


def hash_momcozy_password(password: str) -> str:
    """Reproduce the app's Argon2id password transform and base64 encoding."""
    raw = Argon2id(
        salt=_PASSWORD_SALT,
        length=32,
        iterations=2,
        lanes=1,
        memory_cost=4096,
    ).derive(password.encode())
    return base64.b64encode(raw).decode()


class MomcozyCloudClient:
    """Minimal, read-only account client needed to bootstrap the camera SDK."""

    def __init__(
        self,
        country_code: str,
        language: str = "en",
        time_zone: str = "Europe/Berlin",
        session: aiohttp.ClientSession | None = None,
    ) -> None:
        self._country_code = country_code.upper()
        self._language = language
        self._time_zone = time_zone
        self._device_id = str(uuid4())
        self._session = session
        self._owns_session = session is None

    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        await self.async_close()

    def _headers(self, token: str | None = None) -> dict[str, str]:
        offset = datetime.now(ZoneInfo(self._time_zone)).utcoffset()
        offset_minutes = int(offset.total_seconds() // 60) if offset else 0
        sign = "+" if offset_minutes >= 0 else "-"
        hours, minutes = divmod(abs(offset_minutes), 60)
        time_zone_display = f"GMT{sign}{hours}"
        if minutes:
            time_zone_display += f":{minutes:02d}"
        headers = {
            "Content-Type": "application/json",
            "TimeZone": time_zone_display,
            "ZoneId": self._time_zone,
            "Language": self._language,
            "Version": "3.4.0",
            "Client": "Android",
            "X-COZY-APPID": "momcozy-0719",
            "DeviceType": "1",
            "deviceId": self._device_id,
            "CountryCode": self._country_code,
            "NewFlowEnable": "0",
        }
        if token:
            headers["Authorization"] = f"Bearer {token}"
        return headers

    async def _json(
        self,
        method: str,
        path: str,
        *,
        headers: Mapping[str, str],
        json: Mapping[str, object] | None = None,
    ) -> dict[str, object]:
        if self._session is None:
            self._session = aiohttp.ClientSession()
        try:
            async with asyncio.timeout(_TIMEOUT_SECONDS):
                response = await self._session.request(
                    method,
                    _BASE_URL + path,
                    headers=headers,
                    json=json,
                )
                response.raise_for_status()
                try:
                    payload = await response.json()
                except (aiohttp.ContentTypeError, ValueError) as exception:
                    raise TuyaIpcP2pProtocolError(
                        f"Failed to decode Momcozy response: {exception}"
                    ) from exception
        except (aiohttp.ClientError, TimeoutError) as exception:
            raise TuyaIpcP2pConnectionError(
                f"Failed to call Momcozy {path}: {exception}"
            ) from exception
        if not isinstance(payload, dict):
            raise TuyaIpcP2pProtocolError(
                "Failed to decode Momcozy response: result is not an object"
            )
        code = payload.get("code")
        if code not in (None, 0, "0", 200, "200", "10000000"):
            message = payload.get("message") or "request rejected"
            raise TuyaIpcP2pAuthenticationError(f"Failed to log in to Momcozy: {code}: {message}")
        nested = payload.get("data", payload.get("result", payload))
        if not isinstance(nested, dict):
            raise TuyaIpcP2pProtocolError("Failed to decode Momcozy response: no response data")
        return nested

    async def async_tuya_credentials(self, email: str, password: str) -> _MomcozyTuyaCredentials:
        """Log in to Momcozy and obtain the delegated Tuya UID token."""
        login = await self._json(
            "POST",
            "/api/app/user/login/v3",
            headers=self._headers(),
            json={
                "type": 1,
                "email": email,
                "password": hash_momcozy_password(password),
                "platForm": "BREAST_PUMP",
                "remember": 0,
            },
        )
        bearer = login.get("token")
        if not isinstance(bearer, str) or not bearer:
            raise TuyaIpcP2pProtocolError("Failed to log in to Momcozy: no token")
        tuya = await self._json(
            "GET",
            "/api/app/third/tuya/user",
            headers=self._headers(bearer),
        )
        country_code = tuya.get("region")
        uid = tuya.get("uid")
        token = tuya.get("token")
        if (
            not isinstance(country_code, str)
            or not country_code
            or not isinstance(uid, str)
            or not uid
            or not isinstance(token, str)
            or not token
        ):
            raise TuyaIpcP2pProtocolError("Failed to obtain Tuya credentials: incomplete response")
        return _MomcozyTuyaCredentials(country_code, uid, token)

    async def async_close(self) -> None:
        """Close the HTTP session when this client created it."""
        if self._owns_session and self._session is not None:
            await self._session.close()
            self._session = None
