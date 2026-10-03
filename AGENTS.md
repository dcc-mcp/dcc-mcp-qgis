# Working on dcc-mcp-qgis

Read README.md and docs/ARCHITECTURE.md before changing host integration.

- Core owns MCP, discovery, lifecycle, canonical envelopes, jobs and dispatch queues.
- PyQGIS imports stay lazy. Every host operation executes on the owned process main thread.
- No GUI attachment, network sources, raw execution primary workflow, overwrite-by-default or implicit project loss.
- Keep all workspace path checks and actual effect readback. Bundles are trusted local input; hashes do not authenticate a producer.
- Declare explicit closed input schemas, output schemas, affinity and all safety annotations in bundled skills.
- Preserve vector renderer, labels, draw order and editability through save and reopen.
- Run `python -m ruff check src tests scripts`, `python -m ruff format --check src tests scripts`, and `python -m pytest`.
- Run `python scripts/live_smoke.py --output artifacts/<new-run>` with a QGIS-capable Python for real MCP acceptance. Mock tests do not prove host behavior.
- Do not add release automation or publish artifacts without a separate release request.
