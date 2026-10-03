# Core/server 0.20.41 upgrade candidate

On 2026-10-03, the adapter dependency pins, startup bootstrap minimum and exact
runtime profile were advanced together to the official stable Core/server
0.20.41 releases ([Core](https://pypi.org/project/dcc-mcp-core/0.20.41/),
[server](https://pypi.org/project/dcc-mcp-server/0.20.41/)). A separately
installed official DCC-MCP CLI is managed by the
caller, not added as an adapter dependency. This revision remains a candidate.

## Evidence boundary

The preserved baseline is commit
`08e8ea23efe09bacdc0adacaa87e2e2471d717ec`, using Core/server 0.20.39.
The historical native profile is Linux QGIS 3.40.6-Bratislava, Qt 5.15.15,
Python 3.13.5 and official MCP SDK 2.2.0. VALIDATION.md and
`requirements-validation-0.20.39.txt` describe that earlier profile. They do not qualify
the current source or any 0.20.41 deployment.

The current runtime gate admits only Linux, QGIS 3.40.x, Qt5,
Python 3.10–3.13 and Core/server exactly 0.20.41. Separate Linux native acceptance
passed on exact commit `8b3afd197a24eaaa17a87ad02558855976247fa9`: 113 source tests
and the same 113 tests after a fresh wheel install, actual SDK loops, editable
QGZ save/reopen, PNG byte equality, loopback binding and cleanup. This is not
226 distinct tests and does not qualify other admitted host combinations.
The later geometry-readback correction needs fresh native acceptance on its
own final source and wheel. Windows portable source/package checks use Python 3.12.10 and
MCP SDK 2.2.0 in a fresh isolated environment; this does not admit Windows QGIS
or qualify another SDK/native combination. Exact executed checks and resolved
package versions belong to the separate upgrade receipts, not historical logs.

The profile metadata retains `validated_qgis` as a historical host label,
explicitly pairs it with `native_acceptance_profile` Core/server 0.20.39, and
sets `current_runtime_native_verified` to false. A supported API-family label
is not proof of measured acceptance.

## Executed portable checks

The first isolated Windows source run on 2026-10-03 resolved Core, server and
CLI 0.20.41, official MCP SDK 2.2.0 and Python 3.12.10. Ruff check, Ruff format
check, pytest, wheel build and source distribution build passed. Pytest measured
97 cases: 49 passed and 48 skipped, with no failures. The skips were 47 cases
requiring PyQGIS and one symlink check requiring an unavailable Windows privilege.

The existing capability contract now validates the complete result against the
bundled output schema and distinguishes the current runtime from historical
native acceptance. Exact-profile regressions reject either Core 0.20.39 or
server 0.20.39 paired with the new runtime. No Core 0.20.41 compatibility failure
was observed in these portable checks. Missing PyQGIS prevents native acceptance.
The separate receipt is `checks/qgis/first/checks.json` in the upgrade artifacts;
this result covers source tests and build, not a real QGIS process or remote CI.

## Native acceptance and revalidation

The exact-commit Linux results above are separate from remote CI. Required
portable CI workflows passed on that same commit; its native CI job was skipped.
The geometry regression now retains client WKT length checks while validating
reopened native objects directly. Its high-precision polygon save/reopen test
must execute in QGIS before the corrected revision is native-qualified.

Run source and independent installed-wheel suites with the intended QGIS
interpreter, then run `scripts/live_smoke.py` against a new owned process and
new artifact directory. Repeat installed package lifecycle rehearsal and
verify skill discovery/schema loading, real MCP jobs and cancellation,
geometry/style readback, GeoJSON/GPKG/QGZ/PNG artifacts, loopback listeners,
registry state and shutdown. Retain exact OS, QGIS, Qt, Python, SDK,
Core/server versions and candidate hashes with the results.

Core's localhost defaults do not establish authentication, permission isolation,
embedded fallback safety or listener behavior for this adapter. Existing trusted
local endpoint boundaries and all native/CI/release gates remain applicable.
No native application, user project, global environment, release or remote
repository is changed by this candidate preparation.

## Isolated installation and rollback

Keep the 0.20.39 source commit, wheel and dedicated environment intact. Install
the 0.20.41 candidate wheel into a different dedicated environment using the
same native-compatible QGIS interpreter, then check resolved Core/server
versions before running the native acceptance above. Do not reuse an existing
QGIS GUI session or workspace containing user scenes.

`docs/requirements-validation.txt` pins the current 0.20.41 runtime. To rehearse
a 0.20.39 baseline with `scripts/package_lifecycle.py`, pass
`--baseline-requirements docs/requirements-validation-0.20.39.txt`; the upgrade
stage uses the current validation requirements with the final 0.20.41 wheel.

For rollback, stop the owned candidate process and relaunch the preserved
0.20.39 environment with a new endpoint filename and a new evidence directory.
If that environment must be reconstructed, use the preserved baseline wheel
and exact `dcc-mcp-core==0.20.39` / `dcc-mcp-server==0.20.39` dependencies in a
separate environment. The exact runtime gates reject mixed dependency pairs.
Do not replay a timed-out mutation; inspect its original job and artifacts.
Saved project data remains operator-owned, and rollback is not an unsaved-state
recovery mechanism.
