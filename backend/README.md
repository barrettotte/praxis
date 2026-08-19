# Backend

Python agent and service code lives in `src/praxis`; backend unit tests live in
`tests`. The root `pyproject.toml`, `uv.lock`, and `Makefile` manage the backend
toolchain.

The `praxis` command loads the read-only local catalog and returns exactly three
structured project candidates. It renders readable output by default and accepts
`--json` for machine-readable output and `--data-dir` to override the source
directory.
