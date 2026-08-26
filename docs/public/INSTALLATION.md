# Installation

## Core and development environment

Install Python 3.12 and `uv`, then run:

```bash
uv sync --extra dev --extra web
uv run worldclaw doctor
```

## Web Studio

Install Node.js 20 or newer, then run:

```bash
scripts/setup_web.sh
scripts/start_web.sh
```

The default address is <http://127.0.0.1:7865>. Copy
`webapp/.env.example` to `.env` only if path overrides are required.

## Optional external models

Install SAM 3, SAM 3D Objects and Hunyuan3D 2.1 from their official
repositories. Accept their licenses and configure only local paths; do not put
tokens or checkpoints inside this repository.

Blender is discovered from `PATH` or `WORLDCLAW_BLENDER`. Model interpreters
and checkpoints use the corresponding `WORLDCLAW_*` variables documented in
`webapp/.env.example`.

## GPU profiles

- Core planning/validation: no GPU required.
- Blender Eevee: a supported graphics device is recommended.
- Cycles plus one model stage: NVIDIA GPU with at least 16 GiB recommended.
- Full paper-quality flow: 48 GiB class GPU recommended; stages execute
  serially and unload before the next model begins.

These are engineering recommendations, not upstream model guarantees.

## GPU admission and LAN security

Web Studio runs one GPU stage at a time. Before a job is admitted it reads the
configured GPU's free VRAM and rejects the start with HTTP 409 when the value is
below `WORLDCLAW_MIN_FREE_VRAM_MIB` (12 GiB by default). It never terminates an
unrelated process automatically. Set the threshold to `0` only for an explicit
CPU/non-NVIDIA workflow; otherwise missing GPU telemetry fails closed.

Loopback binding needs no token. A non-loopback `WORLDCLAW_HOST` is refused
unless `WORLDCLAW_API_TOKEN` contains at least 24 characters. Open a protected
Studio once with `?token=...`; the frontend sends a bearer token and the server
sets a 12-hour, HttpOnly, SameSite-strict cookie for images, downloads, and log
streaming. Put TLS in front of the service when traffic leaves a trusted LAN.
