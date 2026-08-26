#!/usr/bin/env python3
"""Compatibility launcher for the packaged ``worldclaw`` command."""

from worldclaw_core.cli import main


if __name__ == "__main__":
    raise SystemExit(main())
