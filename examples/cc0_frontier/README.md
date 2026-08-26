# CC0 Frontier contract fixture

This source-only fixture demonstrates the structured-planning boundary of the
paper reproduction without redistributing model weights, generated meshes, or
third-party textures. It is intentionally small enough for CI.

Generate an equivalent local plan with:

```bash
worldclaw plan \
  --prompt "A meter-scale CC0 frontier valley used to validate the public WorldClaw paper-workflow reproduction" \
  --preset cc0_frontier \
  --seed 260805 \
  --output outputs/cc0_frontier
```

The review gates in `world_spec.json` remain `pending`: a contract fixture is
not evidence that a final rendered scene passed visual or simulation review.

