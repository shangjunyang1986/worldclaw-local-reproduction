# WorldClaw Local Reproduction

Unofficial clean-room engineering reproduction of Tencent Hunyuan's paper
**“WorldClaw: Agentic 3D Open-World Generation at Scale.”**

> 本项目依据论文及公开项目资料独立实现，不是腾讯官方 WorldClaw
> 代码，不包含未公开源码、官方游戏资产或模型权重，也不代表腾讯对本项目的
> 认可、赞助或维护。

WorldClaw Local Reproduction turns a structured scene prompt into an editable
3D world through planning, semantic terrain, reusable assets, regional
composition, 2D-to-3D reconstruction, placement recovery, Blender assembly,
render-based refinement, validation, and web delivery.

Original work:

- Paper: <https://arxiv.org/abs/2608.05248>
- Official project page: <https://tencent-hunyuan.github.io/Hunyuan3D-WorldClaw/>
- Official project repository: <https://github.com/Tencent-Hunyuan/Hunyuan3D-WorldClaw>

This reproduction repository:
<https://github.com/shangjunyang1986/worldclaw-local-reproduction>

## What is reproduced

- versioned `WorldSpec`, asset-registry, measurement and quality contracts;
- semantic-layout and region-aware procedural terrain generation;
- optional SAM 3 text segmentation and SAM 3D Objects reconstruction;
- optional Hunyuan3D 2.1 shape and PBR refinement;
- camera-aware regional placement and Blender scene assembly;
- explicit separation of reference, visual, collision, and navigation layers;
- evidence-backed reference, graybox, material, and final review gates;
- restart-safe local jobs, GPU-aware execution, validation, packaging, and Web Studio;
- browser-safe static previews when WebGL/WebGPU is unavailable.

The paper's private prompts, internal agents, unpublished tools, training data,
and exact configurations are not available. Corresponding components here are
independent engineering substitutes; numerical or pixel-identical equivalence
is not claimed.

## Quick start

Requirements for the core and Web Studio are Python 3.12, `uv`, and Node.js
20 or newer. Blender and the model environments are optional until a workflow
uses them.

```bash
scripts/setup_web.sh
webapp/.venv/bin/worldclaw doctor
scripts/start_web.sh
```

Open <http://127.0.0.1:7865>.

Core-only setup:

```bash
uv sync --extra dev
uv run worldclaw doctor
uv run worldclaw plan --prompt "a forest valley with a river and village"
uv run pytest -q
```

Useful commands:

```text
worldclaw init       create a portable local configuration
worldclaw doctor     inspect Blender, models, checkpoints and GPU availability
worldclaw plan       create a structured deterministic world plan
worldclaw build      build a plan with Blender
worldclaw validate   validate a completed delivery
worldclaw package    create a hash-addressed delivery manifest
worldclaw resume     retry an interrupted Web Studio job
worldclaw serve      start Web Studio
```

See [installation](docs/public/INSTALLATION.md),
[architecture](docs/public/ARCHITECTURE.md),
[reproducibility](docs/public/REPRODUCIBILITY.md),
[paper reproduction boundary](docs/public/PAPER_REPRODUCTION.md),
[release procedure](docs/public/RELEASE.md), and
[asset policy](ASSET_POLICY.md).

## Model boundary

SAM 3, SAM 3D Objects, and Hunyuan3D are external, user-managed dependencies.
This repository does not redistribute their source trees or checkpoints. Users
must obtain them from the official projects, accept their current licenses, and
set paths in `.env` or through `WORLDCLAW_*` environment variables. See
[MODEL_LICENSES.md](MODEL_LICENSES.md).

## Public sample and private case studies

The public sample is an original CC0-compatible frontier-valley fixture. Large
production outputs and branded validation cases such as Honor of Kings and
Denver airport are deliberately excluded from the source distribution. Their
local manifests may be used to test the contract system after an independent
rights review.

## Public release audit

The public tree is built from an explicit allowlist and fails on secrets,
machine-specific paths, symlinks, binary payloads, or files larger than 10 MiB:

```bash
python3 scripts/build_public_release.py --check-only
python3 scripts/build_public_release.py
```

The generated tree is written to
`release_staging/worldclaw-local-reproduction/` with a SHA-256 manifest.

## Citation

Please cite the original paper and identify this repository as an unofficial
reproduction:

```bibtex
@article{guo2026worldclaw,
  title={WorldClaw: Agentic 3D Open-World Generation at Scale},
  author={Guo, Chunchao and Li, Jinpeng and Li, Yang and Huang, Zilong},
  journal={arXiv preprint arXiv:2608.05248},
  year={2026}
}
```

## License

Original repository code and documentation are licensed under Apache-2.0.
Third-party models, assets, inputs, and generated outputs retain their own
terms. See [NOTICE](NOTICE) and
[THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).
