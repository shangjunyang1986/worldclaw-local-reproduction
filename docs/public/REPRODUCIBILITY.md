# Reproducibility contract

Every accepted delivery should record:

- normalized WorldSpec and QualityProfile hashes;
- input file hashes and upstream source identifiers;
- model repository commits and checkpoint SHA-256 values;
- Blender, Python, CUDA and GPU versions;
- prompts, seeds, camera intrinsics/extrinsics and stage arguments;
- stage start/end times, bounded retry history and failure reason;
- visual, collision and navigation artifact hashes;
- review-gate evidence and reviewer identity;
- final BLEND, GLB, render and validation hashes.

The public CPU fixture checks schemas, gates, packaging and deterministic plan
generation. Full visual equivalence requires the separately licensed models and
a supported NVIDIA environment; it is reported as an integration profile, not
hidden behind the basic unit tests.
