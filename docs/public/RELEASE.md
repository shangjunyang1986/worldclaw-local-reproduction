# Public release procedure

1. Run `uv sync --frozen --extra web --extra dev` and the Python test suite.
2. Run the frontend tests and production build from `webapp/frontend`.
3. Run `python scripts/build_public_release.py --check-only`.
4. Build `release_staging/worldclaw-local-reproduction` from the allowlist.
5. Repeat installation, lint, tests, frontend build, and release audit inside
   that clean tree.
6. Publish only the clean tree after adding the final GitHub repository URL and
   reviewing the generated SHA-256 manifest.

Never publish the workspace root directly. The root contains private outputs,
licensed model checkouts, large generated assets, local databases, and branded
case studies that are intentionally outside the source release.

