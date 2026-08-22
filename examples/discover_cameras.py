"""List the account's devices and which of them this SDK can stream."""

from __future__ import annotations

import asyncio

from _credentials import credentials
from tuya_ipc_p2p_sdk import TuyaIpcP2pClient


async def main() -> None:
    email, password, country_code, region = credentials()
    async with TuyaIpcP2pClient(email, password, country_code, region) as client:
        devices = await client.async_list_devices()
        cameras = {camera.device_id for camera in await client.async_discover_cameras()}
        for device in devices:
            mark = "camera" if device.device_id in cameras else "-"
            print(f"{device.device_id}  {mark:7}  {device.category:8}  {device.name}")


asyncio.run(main())
