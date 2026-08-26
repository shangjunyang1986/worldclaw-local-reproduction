# Paper reproduction boundary

This repository is an unofficial clean-room engineering reproduction of
Tencent Hunyuan's *WorldClaw: Agentic 3D Open-World Generation at Scale*. It
uses only the paper, public project pages, public model interfaces, and
independently authored code and assets.

| Paper-level capability | Local implementation | Evidence boundary |
| --- | --- | --- |
| intent and world planning | deterministic plan plus versioned `WorldSpec` | prompt, seed, topology and metric bounds |
| visual references | externally supplied or locally generated reference boards | reference gate; never metric truth |
| region/object understanding | optional SAM 3 adapters | masks and selection metadata |
| 2D-to-3D assets | optional SAM 3D Objects and Hunyuan3D adapters | external model terms; no bundled weights |
| world assembly | deterministic Blender workers | editable BLEND, browser GLB and topology truth |
| iterative validation | geometry, render, simulation, web and four review gates | observations, quality report and hashed manifest |

The upstream private prompts, internal multi-agent implementation, production
asset corpus, training data, and exact configurations are not public. Local
substitutes therefore reproduce the disclosed workflow and observable
contracts; they do not claim source-code identity or pixel-identical output.

Branded and location-specific local validations are private case studies. They
are excluded from the public allowlist and are not evidence of authorization to
redistribute third-party marks, reference images, generated assets, or scenes.

