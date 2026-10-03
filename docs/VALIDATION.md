# Validation evidence

**Historical Core/server 0.20.39 evidence.** This record is preserved without
relabeling its native measurements. Its dependency snapshot is preserved in
`requirements-validation-0.20.39.txt`. Exact-commit 0.20.41 acceptance and the
geometry correction's remaining native revalidation are tracked in the
[runtime upgrade record](RUNTIME_UPGRADE_0_20_41.md).

## Revision 2 numerical and label presentation regressions

The final local revision additionally normalizes safe JSON integers written to
Double fields, compares numeric values canonically across GeoJSON/GPKG, and
keeps PyQGIS text-format parents alive during nested style readback. Typed label
buffer size/color, installed font family and bold styling are now supported.

Source and post-lifecycle installed-wheel suites pass 84 tests. The official SDK
smoke passes number-field integer input, GeoJSON/GPKG export, buffer-free bold
labels, native save/reopen and byte-identical before/after PNGs. The independent
standard package lifecycle also passes after these changes. Tested wheel SHA256:
`64631e4c3bc1c69199402a0c3651624be7c48b0809a9307c8d99191e26a09763`.

Earlier 71-test results below describe the previous hardening revision; they are
not substituted for the revision 2 reruns. Automated Install SOP and remote CI
remain separate gates.


Measured locally on 2026-10-02 against the hardened source and an independent
installed wheel. This is not a published release or a remote CI result.

## Exact measured profile

- Linux, QGIS 3.40.6-Bratislava, Qt 5.15.15, native system Python 3.13.5
- dcc-mcp-core **0.20.39**, dcc-mcp-server **0.20.39**
- Official MCP Python SDK **2.2.0**, protocol **2025-06-18**
- Full native suite: **71 passed** (48 expected QgsField deprecation warnings)
- Independent installed-wheel suite: **71 passed**, package origin verified to
  be wheel site-packages, not source or the earlier editable environment
- Portable subset additionally measured on Python 3.12.14: **37 passed**,
  34 native tests deselected; this does not qualify a Python3.12 native QGIS host
- Ruff check and format check: pass; source distribution and wheel build: pass
- Both installable skill directories pass Core's actual `validate_skill` API

`requirements-validation-0.20.39.txt` records the exact independent wheel-client/test
dependencies. QGIS/Qt/system Python are native prerequisites outside this pip
snapshot. The admitted runtime range is wider than these measured combinations;
see [release-readiness gates](RELEASE_READINESS.md).

## Native HTTP MCP acceptance

The official SDK starts a fresh isolated owned QGIS process, initializes MCP,
searches/loads skills and follows all tools/list pages. Output schemas explicitly
validate either the initial Core async job envelope or the final canonical domain
result. Polling is bounded and follows the original job ID without replay.

The workflow checks eight simultaneous uniquely named layer creations, input
schema failures, project creation, two synthetic parcel polygons, attribute and
geometry edits, category colors/labels, GeoJSON export, QGZ/GPKG save, stale-ID
rejection after reopen, exact value/area readback and two byte-identical 900×600
PNG renders before and after reopen. The same workflow passes against the
independent installed wheel.

- Source evidence: `artifacts/source-live-final/result.json`
- Installed-wheel evidence: `artifacts/wheel-live-final/result.json`
- Each directory contains endpoint/listener evidence, server log, native project
  bundle, GeoJSON and before/after PNGs
- The smoke inspects every process-owned Linux TCP listener and accepts only
  127.0.0.1; SIGTERM must exit zero, close the TCP endpoint and remove any instance
  registry record
- Every run has a new workspace, process, endpoint and identity. No open desktop
  project, user dataset or external service is read or changed

## Regression and native safety coverage

- Independent main-thread guards, closed-session errors, idempotent close and
  exclusive endpoint-file creation with failure cleanup
- Twelve concurrent dispatcher calls retain their own marker/result identities
- A timed-out queued callback is explicitly cancelled and cannot mutate when the
  queue is pumped later; queued cancellation and shutdown also reject work
- Cancelling after native vector writing removes staging output and prevents
  publication; cancellation before feature commit rolls back the edit buffer
- An official SDK/real Core HTTP test pauses after an actual native export writes
  staging data, cancels that same job via DELETE /v1/jobs/{id}, resumes the native
  callback and verifies no publication. A later main-affinity query proves cleanup
  completed; the original live project remains usable
- Full WKB geometry and user-attribute readback on insertion/export/save/reopen;
  a writer that preserves counts while corrupting values is rejected
- Native roundtrip preserves string/Unicode, 64-bit integer, floating-point and
  boolean values; a valid no-field vector can be created and edited
- Styling reads back symbol properties, category values and label settings;
  duplicate categories and malformed style inputs do not mutate
- 1 MiB aggregate request cap, finite JSON, ±1e9 coordinate bound, bounded fields,
  features, archive members and uncompressed/total bundle sizes
- Malformed/null/list manifests, duplicate manifest keys, malformed digests,
  traversal ZIP entries, symlinks, invalid CRS/geometries and stale IDs fail closed
- File publication never replaces an existing path; bundle publication uses
  atomic Linux no-replace rename and preserves even a concurrently created empty
  destination directory
- Save/reopen retains styles, labels, draw order and editable in-memory copies;
  editing the reopened project does not modify saved GeoPackages

## Reproduce

Use the QGIS-compatible interpreter and dedicated environment from INSTALL.md.
The commands below use the current 0.20.41 requirements. Replaying a historical
0.20.39 wheel requires `docs/requirements-validation-0.20.39.txt` instead.
The native gate must not silently skip when QGIS is absent:

```sh
python -m ruff check src tests scripts
python -m ruff format --check src tests scripts
DCC_MCP_QGIS_REQUIRE_NATIVE=1 python -m pytest
python scripts/live_smoke.py --output artifacts/new-source-run
uv build --python /path/to/qgis-python --out-dir artifacts/dist
uv venv --python /path/to/qgis-python --system-site-packages .wheel-venv
uv pip install --python .wheel-venv/bin/python artifacts/dist/*.whl -r docs/requirements-validation.txt
.wheel-venv/bin/python -c "import dcc_mcp_qgis; print(dcc_mcp_qgis.__file__)"
DCC_MCP_QGIS_REQUIRE_NATIVE=1 .wheel-venv/bin/python -m pytest
.wheel-venv/bin/python scripts/live_smoke.py --output artifacts/new-wheel-run
```

Unset source-tree PYTHONPATH before independent wheel acceptance. An already
installed uv avoids requiring ensurepip or modifying the system interpreter.
CI config now separates automatic portable tests from a manually requested,
operator-provisioned native runner; both exercise an installed wheel. Native
CI has not run remotely and no runner availability is claimed.

## Remaining boundaries

Native APIs remain monolithic. Checkpoints prevent admission, edit-buffer commit
or final publication after an observed cancellation, but cannot preempt a native
call already running or undo a commit that wins a race. A timeout is not proof
that a mutation failed: query the existing job and inspect state. No hard-abort,
rollback of arbitrary native work, durable cross-restart recovery, broad MCP
certification or hostile-project sandbox is claimed.

Shared Install SOP transactional lifecycle/rollback integration and reviewed
release/remote CI are still separate gates. The honest release-readiness matrix
must be reviewed before using the word production-ready.

## Standard package lifecycle rehearsal

`scripts/package_lifecycle.py` creates a fresh isolated environment using the
operator's QGIS-capable Python. It installs the frozen baseline wheel, explicitly
reinstalls the hardened wheel at the same pre-release version, and compares every
installed source/skill file hash to the final source. A corrupt-wheel replacement
must fail while preserving all previous installed files. It then uninstalls the
package, proves import is unavailable from a clean directory, reinstalls the final
wheel and reruns the full native suite plus official-SDK MCP acceptance.
When the baseline wheel requires Core/server 0.20.39, supply
`--baseline-requirements docs/requirements-validation-0.20.39.txt`. The upgrade
stage resolves the final wheel with the current 0.20.41 requirements.

Evidence: `artifacts/package-lifecycle-final/result.json` and per-stage logs.
This verifies standard package-manager lifecycle and failed artifact preparation;
it does not implement shared Core Install SOP receipts, deployment transaction
rollback, or guarantee arbitrary interrupted filesystem-install recovery.
