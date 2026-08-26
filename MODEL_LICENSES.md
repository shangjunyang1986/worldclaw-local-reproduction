# Model installation and license boundary

WorldClaw Local Reproduction treats all foundation models as external services
or user-managed installations. Setup commands must never embed access tokens or
redistribute gated checkpoints.

## SAM 3 and SAM 3D Objects

Both are governed by Meta's SAM License. Users must obtain the code and weights
from the official repositories, accept the applicable terms, and configure the
local interpreter/checkpoint paths. The public release contains adapters only.

## Hunyuan3D 2.1

Hunyuan3D 2.1 is governed by the Tencent Hunyuan 3D 2.1 Community License,
including its territory, use, attribution, and distribution conditions. The
public release does not bundle Hunyuan source code, weights, or a model-derived
asset pack. Users are responsible for confirming that their location and use
are permitted by the current upstream license.

## Version lock

`worldclaw doctor --json` reports the configured executable paths. A release
provenance file should additionally record upstream repository URLs, exact Git
commits, checkpoint identifiers, and SHA-256 digests for each local run.
