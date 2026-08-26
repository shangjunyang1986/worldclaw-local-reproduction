# Architecture

WorldClaw Local Reproduction is organized around immutable stage inputs and
versioned contracts:

```text
Prompt
  -> intent / WorldSpec
  -> semantic layout and terrain
  -> regional composition
  -> segmentation and object reconstruction
  -> camera-aware placement
  -> Blender assembly
  -> bounded render-based refinement
  -> quality gates and delivery manifest
  -> Web Studio
```

`worldclaw_core` owns contracts, gates, provenance, adapters, CLI behavior and
portable configuration. `webapp/backend` owns job persistence, safe process
execution and the single-GPU queue. `webapp/frontend` owns review, evidence,
preview and downloads. Blender scripts are executable workers and should not
contain workstation-specific paths.

Reference imagery is evidence, visual geometry is renderable appearance,
simulation geometry is collision truth, and navigation truth is a separate
authoritative layer. Generated images cannot silently become metric truth.

The browser creates no graphics context until the user opens the 3D preview.
Only one Three.js renderer can hold a context at a time; switching jobs or tabs
disposes geometry, materials, textures, renderer caches, and the context. A
context failure falls back to a lazily decoded multi-view render sequence.

The backend owns a single serial GPU worker and publishes its current job,
queue depth, and free-VRAM admission state at `/api/resources`. Authentication
is optional on loopback and mandatory-by-launch-policy for LAN binding.
