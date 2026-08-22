"""Stream the first camera and print a line per frame, with the motion state."""

from __future__ import annotations

import asyncio
import logging

from _credentials import credentials
from tuya_ipc_p2p_sdk import TuyaIpcP2pClient

logging.basicConfig(level=logging.DEBUG)


async def main() -> None:
    email, password, country_code, region = credentials()
    async with TuyaIpcP2pClient(email, password, country_code, region) as client:
        cameras = await client.async_discover_cameras()
        if not cameras:
            raise SystemExit("No camera on this account answers the IPC config API")
        camera = cameras[0]

        stream = client.create_camera_stream(camera.device_id, camera.local_key)
        await stream.async_start()
        try:
            async for frame in stream.async_frames():
                motion = "motion" if stream.motion_detected else ""
                print(f"{len(frame):>7} bytes  {motion}")
        except KeyboardInterrupt:
            pass
        finally:
            await stream.async_stop()


asyncio.run(main())
