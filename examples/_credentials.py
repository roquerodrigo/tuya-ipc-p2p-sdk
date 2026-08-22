"""Reads the account credentials every example needs out of the environment."""

from __future__ import annotations

import os

from dotenv import load_dotenv

load_dotenv()


def credentials() -> tuple[str, str, str, str]:
    """Return email, password, country code and region, or explain what is missing."""
    email = os.environ.get("TUYA_EMAIL", "")
    password = os.environ.get("TUYA_PASSWORD", "")
    country_code = os.environ.get("TUYA_COUNTRY_CODE", "")
    region = os.environ.get("TUYA_REGION", "us")
    missing = [
        name
        for name, value in (
            ("TUYA_EMAIL", email),
            ("TUYA_PASSWORD", password),
            ("TUYA_COUNTRY_CODE", country_code),
        )
        if not value
    ]
    if missing:
        message = f"Set {', '.join(missing)} in the environment or in a .env file"
        raise SystemExit(message)
    return email, password, country_code, region
