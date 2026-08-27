# Documentation showcase provenance

These files are compressed documentation previews of Blender renders produced
by the local WorldClaw reproduction workflow. They are not reference images,
downloadable model assets, or substitutes for the omitted production scenes.

## `frontier-valley-cycles.webp`

- Stable ID: `worldclaw-doc-preview.frontier-valley-cycles.v1`
- Source URL: <https://github.com/shangjunyang1986/worldclaw-local-reproduction/tree/main/docs/public/assets>
- Author: WorldClaw Local Reproduction contributors
- SPDX license expression: `Apache-2.0 AND CC0-1.0 AND LicenseRef-Tencent-Hunyuan-3D-2.1-Community`
- Source render: `outputs/frontier_valley_hq_v4_cycles_test/global.png`
- Source render SHA-256: `7d0205871f05b2b40e851645ca7d37005e608ce8bc7628104bee641728fa8f10`
- Local WebP SHA-256: `31f15a68c1fe0ad9da5b482183cdcf85e7d184e28c0dc43daa12d4ee0ab444b6`
- Modification: Lanczos downscale from 1920×1080 to 1600×900; lossy WebP,
  quality 82, YUV 4:2:0.
- Components: project-authored world composition and procedural assembly;
  CC0 Poly Haven material/environment inputs; locally generated Hunyuan3D
  assets governed by the upstream community license.
- Allowed use: documentation and review of this repository, subject to every
  listed component license. This record does not authorize redistribution of
  the omitted scene, source assets, or model weights.

The source manifest records Blender Cycles rendering, 4,236 scene objects,
regional terrain, river, vegetation, village, bridge, watchtower, and windmill
placement.

## `dense-urban-helipad.webp`

- Stable ID: `worldclaw-doc-preview.dense-urban-helipad.v1`
- Source URL: <https://github.com/shangjunyang1986/worldclaw-local-reproduction/tree/main/docs/public/assets>
- Author: WorldClaw Local Reproduction contributors
- SPDX license expression: `Apache-2.0 AND CC0-1.0`
- Source render: `outputs/bo105_u01_dense_urban_v3/renders_final/U01V3_helipad_precision.png`
- Source render SHA-256: `86eac94c1b539743ff72c8b2d03bea7d5ffb5f740155f3248c5ef609b5e6e74d`
- Local WebP SHA-256: `dff22adbc34fa1b5f4c4273a4eb51f66254dd3d3f77e1daab3d8aac67ef1c793`
- Modification: Lanczos downscale from 3840×2160 to 1600×900; lossy WebP,
  quality 82, YUV 4:2:0.
- Components: project-authored explicit metric geometry and composition; CC0
  Poly Haven assets; project-generated facade textures used only for material
  appearance.
- Allowed use: documentation and review of this repository. No production
  BLEND/GLB scene or texture source is redistributed by this preview.

The frozen geometry audit reports a 16.5 m helipad surface radius, a maximum
outer-circle radial error of 0.000014120869 m, and zero measured planarity error
on all four audited hospital roof surfaces.

## `dense-urban-crane.webp`

- Stable ID: `worldclaw-doc-preview.dense-urban-crane.v1`
- Source URL: <https://github.com/shangjunyang1986/worldclaw-local-reproduction/tree/main/docs/public/assets>
- Author: WorldClaw Local Reproduction contributors
- SPDX license expression: `Apache-2.0 AND CC0-1.0`
- Source render: `outputs/bo105_u01_dense_urban_v3/renders_final/U01V3_crane_rigid_structure.png`
- Source render SHA-256: `5ca97cf061a32424bda4a5460d2c69ecceb177792c5273961c37e9d4f6bb7288`
- Local WebP SHA-256: `a0ebabd3a3280cdd6a706b2a63afbfdedff85a9916020b3e0b5d49eef4315880`
- Modification: Lanczos downscale from 3840×2160 to 1600×900; lossy WebP,
  quality 82, YUV 4:2:0.
- Components: project-authored explicit metric geometry and composition; CC0
  Poly Haven assets; project-generated facade textures used only for material
  appearance.
- Allowed use: documentation and review of this repository. No production
  BLEND/GLB scene or texture source is redistributed by this preview.

The frozen geometry audit reports a 94 m crane mast, an 87 m front jib, a 24 m
counter-jib, and eleven explicitly straight principal beams.

## Rights boundary

Apache-2.0 covers the repository's original documentation and project-authored
portions. CC0-1.0 covers identified Poly Haven inputs. Model-generated or
third-party portions remain subject to their upstream terms. Inclusion of a
render does not relicense any upstream model, source asset, trademark, or
omitted production deliverable.
