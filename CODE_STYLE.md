# Code Style Guide

Style conventions for `tuya-ipc-p2p-sdk`. Before committing, run
`uv run ruff format --check .`, `uv run ruff check .` and `uv run mypy src` —
all must exit cleanly. `uv run pytest` (with the 90 % coverage gate) follows.

**Always read this file before adding or restructuring code.**

## Language

- Code is written in **English**: file names, class names, function names,
  variable names, dictionary keys, identifier strings.
- The conversation language with the user can be Portuguese or anything else;
  what is committed to disk stays English.

## File organization

- **`src/` layout.** The package is importable only after an (editable)
  install, which keeps the test suite honest about what actually gets packaged.
- **One top-level class per file**, including dataclasses. Semantically related
  classes get a package directory with one class per submodule and an
  `__init__.py` re-exporting the public symbols — `exceptions/`, `models/`,
  `gateway/`, `signaling/`, `transport/`.
  - **Relaxation**: a private leaf dataclass used by exactly one module may
    live in that module (`_PendingSegment` in `transport/kcp_conversation.py`,
    `ControlPacket` in `control.py`).
- **Modules of functions are fine** when the subject is a wire format rather
  than an object: `crypto.py`, `media.py`, `gateway/signing.py`,
  `signaling/envelope.py`, `transport/relay_framing.py`.
- `__init__.py` at the package root re-exports the whole public surface, so the
  module layout stays free to change without breaking consumers.

## Naming

- Public classes are prefixed with `TuyaIpcP2p` where the name would otherwise
  be ambiguous outside the package (`TuyaIpcP2pClient`, every exception).
  Protocol objects keep the name the protocol gives them (`RelayToken`,
  `KcpConversation`, `StreamSession`).
- Coroutine methods on the public surface are prefixed `async_`, matching what
  the consuming Home Assistant integration expects.
- Exception classes end with `Error`.
- Private attributes and functions are prefixed with `_`.

## Typing

**Strict typing. No `Any`.** `mypy --strict` runs with
`disallow_any_explicit = true`, so `typing.Any` cannot appear at all.

- JSON crossing the gateway or the signaling boundary is typed through the
  `type` aliases in `json_types.py` (`JsonPrimitive`, `JsonValue`,
  `JsonObject`) and read through its accessors (`require_str`,
  `optional_object`, `object_list`, …) rather than indexed directly.
- `@dataclass(frozen=True, slots=True)` for wire records under `models/`.
- `frozenset[str]` / `tuple[str, ...]` for fixed string collections.
- Type-only imports go in a `TYPE_CHECKING` block; every module starts with
  `from __future__ import annotations`.

## Docstrings

- Every public class, function, method and `__init__` has a docstring; every
  module has a module docstring. Ruff enforces this.
- Describe the *contract* or the *why*, not the obvious implementation, and do
  not restate the type — the signature already does.

## Comments

- Default to **no comments**. Add one only when the *why* is not obvious: a
  hidden protocol constraint, a workaround, a subtle invariant.
- Never describe *what* the code does — well-named identifiers handle that.
- No section dividers. If a file needs them, split it.
- The protocol's non-obvious requirements *are* worth a comment, and the module
  docstrings carry the layout each file implements.

## Logging

- Use the package-level `LOGGER` from `const.py`; never call
  `logging.getLogger(...)` ad hoc.
- Use lazy `%`-formatting, never f-strings.
- Levels: `debug` for per-session protocol detail, `info` for one-shot
  lifecycle, `warning` for recoverable failures.
- **Never log secrets** — the local key, the device password, the relay
  credential, the account password or the session `sid`/`ecode`.

## Error messages

- Format: `"Failed to <verb> <object>: <cause>"`. Keep them short and
  grep-able.
- The exception hierarchy is `TuyaIpcP2pError` (base) →
  `…ConnectionError` (timeout, DNS, a transport that dropped),
  `…AuthenticationError` (credentials rejected),
  `…GatewayError` (the API answered with a refusal),
  `…ProtocolError` (a frame or record that does not decode) and
  `…SessionError` (a session that could not be established or was torn down).
- Wrap upstream errors at the boundary; nothing above catches `aiohttp` or
  `aiomqtt` types.

## Public API surface

- Everything a consumer imports is re-exported from `tuya_ipc_p2p_sdk/__init__.py`
  and listed in `__all__`. Anything not there is internal and may move.
- The SDK knows nothing about Home Assistant: no entities, no coordinators, no
  config entries. It takes credentials and returns frames.

## Dependencies

**Runtime dependencies are never pinned with `==` and never capped.** Home
Assistant pins its own transitive dependencies exactly, so an SDK that pins — or
caps — a library HA also ships eventually contradicts HA's pin and the
integration fails to install. Use a `>=` floor only. Exact versions belong in
the dependency groups and `uv.lock`, neither of which reaches the consumer.

## Testing

- Tests live in `tests/`, are **network-free** apart from loopback sockets, and
  never depend on real credentials or reachable hardware.
- The protocol vectors — signatures, key derivations, envelope bytes, the
  channel-0 packet layout — are pinned against the Go reference client. Never
  "fix" a vector to match a code change; the vector is the specification.
- The fakes (`tests/fake_relay.py`, `tests/fake_mqtt.py`) implement the device
  side of the protocol, so the session tests exercise the real transport rather
  than a mock of it.
- The 90 % coverage gate (`pyproject.toml`) prevents untested code from
  sneaking in.

## Conventional commits

All commits follow [Conventional Commits](https://www.conventionalcommits.org/),
which `release-please` parses to bump the version and generate `CHANGELOG.md`.
Subject line: imperative mood, lowercase, no trailing period. `feat` bumps the
minor, `fix`/`perf`/`deps` the patch, and a `BREAKING CHANGE:` footer the major.

## Pre-commit hooks

`.pre-commit-config.yaml` runs ruff format, ruff check and mypy as **local
hooks through `uv run`**, so every commit uses the exact tool versions pinned in
`pyproject.toml`/`uv.lock` — the ones CI resolves. Never switch these to
mirrored hooks, which carry their own version pin and silently drift. Install
once per clone with `pre-commit install`.
