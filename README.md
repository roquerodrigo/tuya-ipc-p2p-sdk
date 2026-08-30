# tuya-ipc-p2p-sdk

[![CI](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk/actions/workflows/ci.yml/badge.svg)](https://github.com/roquerodrigo/tuya-ipc-p2p-sdk/actions/workflows/ci.yml)
[![PyPI](https://img.shields.io/pypi/v/tuya-ipc-p2p-sdk)](https://pypi.org/project/tuya-ipc-p2p-sdk/)

Async Python SDK for the **native P2P video** of Tuya IPC cameras — the path the
vendor app uses, spoken directly by this package. No vendor SDK, no external
process and no cloud RTSP: it logs in, negotiates the session, decrypts the
media and hands you JPEG frames.

> ⚠️ **Unofficial.** This project is not affiliated with, endorsed by or
> supported by Tuya. It targets the mobile API gateway and the P2P protocol
> their app uses. The vendor can change either side at any time and break this
> SDK without notice.

The official Tuya integrations stream these cameras over a cloud RTSP link,
which several devices — pet feeders and other low-cost IPC hardware among
them — do not offer. This SDK speaks the P2P protocol those devices *do*
answer.

## Status

**Alpha** — usable but not yet stable.

| Area | State |
|---|---|
| Email/password login against the mobile gateway | ✅ |
| Camera discovery (devices that answer the IPC config API) | ✅ |
| Signaling over MQTT, offer/answer, trickled candidates | ✅ |
| TCP relay transport (handshake, keepalive, tagged KCP frames) | ✅ |
| Channel-0 authentication and the start burst | ✅ |
| MJPEG frames, reassembled by chunk offset | ✅ |
| Supervised reconnects, stall detection, backoff | ✅ |
| Motion derived from frame sizes | ✅ |
| Audio (conversation 2) | ⚠️ received and discarded |
| The channel-0 control surface | ⚠️ decoded but not exposed |
| H264 cameras | ❌ untested — validated against MJPEG hardware only |
| Regions other than `us` | ⚠️ declared, only `us` is exercised live |
| Public API stability | ❌ breaking changes still happen across `0.x` |

See [`CHANGELOG.md`](./CHANGELOG.md) for breaking changes between releases.

## Install

```bash
pip install tuya-ipc-p2p-sdk
```

Or, with [uv](https://docs.astral.sh/uv/):

```bash
uv add tuya-ipc-p2p-sdk
```

## What you need

- The account the camera belongs to: **email**, **password** and the
  **country code** (the calling code — `1` for the US, `55` for Brazil).
- The **region** its gateway lives in (`us` by default).

The device id and its local key are discovered from the account; nothing has to
be copied out of the app by hand.

## Usage

```python
import asyncio

from tuya_ipc_p2p_sdk import TuyaIpcP2pClient


async def main() -> None:
    async with TuyaIpcP2pClient("you@example.com", "secret", "55") as client:
        cameras = await client.async_discover_cameras()
        camera = cameras[0]
        print(camera.name, camera.device_id)

        stream = client.create_camera_stream(camera.device_id, camera.local_key)
        await stream.async_start()
        try:
            frame = await stream.async_wait_for_frame(45)
            if frame:
                print(f"first JPEG: {len(frame)} bytes")
            async for jpeg in stream.async_frames():
                print(len(jpeg), "motion" if stream.motion_detected else "")
        finally:
            await stream.async_stop()


asyncio.run(main())
```

`async_frames()` starts with the most recent frame and then yields every new
one. Several consumers can read it at once; each gets its own shallow queue, so
a slow reader skips ahead rather than falling behind.

Runnable scripts live in [`examples/`](./examples).

## Cameras serve one client at a time

While a stream is running the vendor app cannot connect to that camera, and
while the app holds it this SDK cannot. Bringing a cold session up takes several
seconds — login, signaling, relay, the channel-0 handshake — so a consumer that
wants video ready on demand keeps the stream running rather than starting it per
request.

## Motion

These cameras report no motion of their own. A JPEG is only as large as its
content is complex, so how much each frame differs in size from the one before
it is a direct measure of how much the scene changed — and it costs nothing,
because the frames arrive either way.

Measured against a still scene on real hardware, consecutive frames differ by
0.2 % in daylight and 0.41 % at night, where sensor noise is higher. The typical
difference is tracked continuously rather than fixed, so the threshold follows
the camera from day into night, and `motion_sensitivity` sets how far above
typical a frame has to land. Two frames in a row have to exceed it: anything
really moving stays in shot longer than one frame, while the camera's own
exposure adjustments show up as a single frame that differs sharply from both
its neighbours.

It cannot tell a cat from the lights coming on. On a still scene at night — the
noisiest case — the default settles at about one event every ten minutes; raise
the sensitivity if that is too eager.

## How it works

The native P2P path is WebRTC-shaped signaling with a custom media transport:

1. **Login and config.** A signed, encrypted (`et=3`) call to the mobile
   gateway logs in; `m.ipc.v4.rtc.config.get` returns a server-coordinated
   session, the ICE servers and a relay token. Each fetch mints a fresh
   session — a camera does not answer an offer built from a stale one — so
   every reconnect refetches it.
2. **Signaling.** An SDP offer/answer is exchanged as JSON over MQTT, inside a
   binary "2.2" envelope whose body is AES-ECB'd with the device local key. The
   media line negotiates `AES/KCP` rather than DTLS-SRTP.
3. **Transport.** Media flows over the TCP relay named in the offer: one
   connection multiplexes several KCP conversations — control on conversation
   0, video on 1, audio on 2 — each frame authenticated by a per-frame HMAC
   tag.
4. **Media.** After a channel-0 authentication the camera starts sending. The
   records are AES-128-CBC, and the video conversation reassembles into JPEG
   frames by chunk offset.

**The ICE role matters.** The device runs its connectivity checks as the
*controlling* agent even though the client is the offerer, and it waits for that
negotiation to conclude before committing media. A client that also claims the
controlling role produces a role conflict the device never resolves: it sends
the first frames and then tears the session down with `close_reason=6` seconds
later. This SDK answers the checks as the *controlled* agent, which keeps
sessions up indefinitely. Media itself rides the relay, so no candidate pair has
to be nominated for video to flow.

The byte-level protocol reference lives in the companion Go client,
[`tuya-ipc-p2p`](https://github.com/roquerodrigo/tuya-ipc-p2p) (`PROTOCOL.md`).
This package is an independent Python implementation of the same protocol, and
its tests pin the shared vectors — signatures, key derivations, envelope bytes
and the channel-0 packet layout — against that reference.

## Staying up

Each session ends on transport close, a device disconnect, or a stall (no frame
within the stall timeout). The supervisor then backs off, fetches a fresh config
and starts over, resetting the backoff after any session that actually streamed
and logging in again if the gateway rejects the session. Every session publishes
a `disconnect` on its way out, so the device releases it rather than refusing
the next offer.

## A camera that stops answering

A device that is still holding a session answers the next offer with
`close_reason=12`, which `TuyaIpcP2pDeviceBusyError` reports. One of those is
ordinary — the next attempt gets in. A run of them is not: after about a dozen
back-to-back attempts these cameras stop answering offers from *any* client,
the vendor app included, and stay that way until the hardware is power cycled.

`CameraStream.needs_power_cycle` reports that state after
`busy_refusal_limit` consecutive busy replies, and the supervisor stops
offering every minute — it waits `refused_retry_seconds` between attempts,
since offering into that state is what holds it there. Any session that streams
clears it. A consumer can surface it: the Home Assistant integration turns it
into a repair issue telling the user to power cycle the camera.

## Layout

```
src/tuya_ipc_p2p_sdk/
├── client.py            the entry point: one account, its cameras, its streams
├── camera_stream.py     keeps one camera streaming and fans its frames out
├── stream_session.py    one session end to end
├── motion_detector.py   motion read out of frame sizes
├── control.py           channel-0 auth and the start burst
├── media.py             channel-1 packet extraction
├── jpeg_reassembler.py  JPEG frames rebuilt by chunk offset
├── crypto.py            AES-CBC records, the AES-ECB envelope, PKCS#7
├── json_types.py        the JSON boundary and its accessors
├── gateway/             request signing, encrypted bodies, login, config fetch
├── signaling/           SDP, the MQTT envelope, the signaling client, handshake signing
├── transport/           TCP relay framing, KCP, the controlled-role ICE responder
├── models/              the typed records the SDK hands back
└── exceptions/          the error hierarchy
```

## Development

```bash
uv sync
./scripts/lint      # ruff format, ruff check, mypy, pytest
```

The suite is network-free: a fake relay server speaks the handshake and media
framing over loopback, and a fake broker stands in for MQTT, so the session
tests exercise the real transport rather than a mock of it.

## License

MIT — see [`LICENSE`](./LICENSE).
