"""Bring the first camera up and write one JPEG to disk."""

from __future__ import annotations

import asyncio
from pathlib import Path

from _credentials import credentials
from tuya_ipc_p2p_sdk import TuyaIpcP2pClient

WARMUP_SECONDS = 60


async def main() -> None:
    email, password, country_code, region = credentials()
    async with TuyaIpcP2pClient(email, password, country_code, region) as client:
        cameras = await client.async_discover_cameras()
        if not cameras:
            raise SystemExit("No camera on this account answers the IPC config API")
        camera = cameras[0]
        print(f"Streaming {camera.name} ({camera.device_id})")

        stream = client.create_camera_stream(camera.device_id, camera.local_key)
        await stream.async_start()
        try:
            frame = await stream.async_wait_for_frame(WARMUP_SECONDS)
            if frame is None:
                raise SystemExit("The camera produced no frame; is the app holding it?")
            destination = Path(f"{camera.device_id}.jpg")
            destination.write_bytes(frame)
            print(f"Wrote {destination} ({len(frame)} bytes)")
        finally:
            await stream.async_stop()


asyncio.run(main())
