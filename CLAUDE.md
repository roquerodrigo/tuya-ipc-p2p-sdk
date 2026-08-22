# tuya-ipc-p2p-sdk

Async Python SDK for the **native P2P video** of Tuya IPC cameras (`p2pType 4`) —
the path the vendor app uses, spoken directly. It logs in to the mobile gateway,
negotiates the session over MQTT, dials the TCP relay, authenticates on channel 0
and decrypts the media into JPEG frames. No vendor SDK, no external process and
no cloud RTSP.

The byte-level reference for the protocol is the companion Go client,
[`tuya-ipc-p2p`](https://github.com/roquerodrigo/tuya-ipc-p2p) (`PROTOCOL.md`).
This package is an independent Python implementation of the same protocol, and
its tests pin the shared vectors — signatures, key derivations, envelope bytes,
the channel-0 packet layout — against that reference.

## Always read `CODE_STYLE.md` first

Before creating, renaming or restructuring any file/class/function, **read
[`CODE_STYLE.md`](./CODE_STYLE.md)**. It is the single source of truth for
conventions: language, file organisation, naming, typing, imports, docstrings,
comments, logging, error messages, public API surface, conventional commits,
packaging, testing, lint workflow.

## Verification workflow

After every code change, always run lint then tests, in that order, before
declaring the task done. `scripts/lint` is a thin wrapper that only chains the
four commands:

```bash
uv run ruff format --check .
uv run ruff check .
uv run mypy src
uv run pytest
```

Both gates mirror CI. `pytest` enforces a 90 % coverage gate. Skip this only
when the change literally cannot affect lint or tests (e.g. README-only edits).

## What the tests can and cannot reach

The suite is network-free and still exercises the protocol end to end: a fake
relay server (`tests/fake_relay.py`) speaks the f4 handshake and the f6 media
framing over a real loopback socket, and a fake broker (`tests/fake_mqtt.py`)
stands in for aiomqtt. A change to the framing, the KCP bookkeeping or the
session order is caught by them; a change to what the *device* does is not, and
has to be validated against real hardware.

## Protocol invariants that look like bugs

These are the details a well-meaning refactor breaks. All of them cost a live
session to rediscover:

- **Refetch the config per session.** The P2P session, its media key and the
  relay token are minted per fetch. A camera does not answer an offer built
  from a stale one.
- **Offer a freshly minted relay rendezvous id**, not the `sessionId` the
  config's `tcpRelay` carries — that one embeds the token expiry. The same
  minted value has to go into the relay handshake.
- **Take the controlled ICE role.** The device runs its checks as the
  controlling agent even though the client is the offerer. Claiming the role
  too makes it tear the session down with `close_reason=6` seconds after the
  first frames.
- **Service every conversation the device opens.** An unserviced one stalls the
  device's sender for the whole session, which stops the video too — including
  the audio conversation nothing reads.
- **The signaling tunnel is fire-and-forget.** The device never acknowledges
  conversation `0x010000f3`, so its segments are hand-built and sent exactly
  once. A retransmitting sender replays the offer, and a replayed offer stops
  the stream.
- **Pad the tunnel message once, as a whole**, then split it into records.
  Padding each chunk injects pad bytes mid-message and the device discards it.
- **Tag every f6 frame.** A device silently drops an f6 whose HMAC-SHA1 tag is
  missing or wrong: the connection stays up and nothing else happens.
- **Publish a `disconnect` on the way out.** Without it the device holds the
  session and refuses the next offer until its own timer fires.

## Downstream consumer

This package is published to PyPI and consumed by the `ha-tuya-ipc-p2p` Home
Assistant integration (sibling repo), which pins an **exact** version
(`tuya-ipc-p2p-sdk==X.Y.Z`) in both its `pyproject.toml` dev group and
`custom_components/tuya_ipc_p2p_sdk/manifest.json`. A release here does not reach
the integration until that pin is bumped there.
