# Public asset policy

The Git repository is source-first. It contains only small fixtures that are
original, procedural, or explicitly cleared for redistribution.

Small, curated WebP renders may be included under `docs/public/assets/` for
documentation. Each one must have a provenance record, a source-render hash,
a local hash, a modification record, an explicit license expression, and a
plain-language allowed-use statement. A documentation preview does not make
the underlying model, texture pack, or production scene redistributable.

The following are excluded by default:

- official reference screenshots and project-page media;
- extracted or recreated branded game assets;
- model checkpoints and upstream model repositories;
- local BLEND/GLB/PLY outputs and render archives;
- generated assets without an explicit provenance record;
- assets with ambiguous, non-redistributable, or location-restricted terms.

Every redistributable asset must have a stable ID, source URL, author, SPDX
license expression, source SHA-256, local SHA-256, modification record, and a
plain-language allowed-use statement. "Project generated asset" is not a valid
license expression.

Honor of Kings and Denver airport scenes are local validation case studies.
They may be documented through independently produced, legally reviewed media,
but are not part of the default public sample or source distribution.
