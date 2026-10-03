# Release-readiness gates

This is a hardened pre-release source candidate. Do not equate one Linux smoke
with production readiness, remote CI success, a public release or protocol
certification.

Separate Linux acceptance with Core/server 0.20.41 passed against exact commit
`8b3afd197a24eaaa17a87ad02558855976247fa9`: 113 source tests and the same 113 tests
from a fresh installed wheel, actual SDK loops, editable QGZ save/reopen,
byte-identical PNGs, loopback binding and cleanup. These are two executions of
the same suite, not 226 distinct tests. The geometry-readback correction after
that commit requires new source and installed-wheel native acceptance; prior
results do not qualify changed code. See the
[runtime upgrade record](RUNTIME_UPGRADE_0_20_41.md).

## Runtime qualification versus measured acceptance

- Startup-admitted API family: Linux, QGIS 3.40.x, Qt5, Python 3.10–3.13,
  dcc-mcp-core and dcc-mcp-server exactly 0.20.41
- Historical native measured combination: QGIS 3.40.6-Bratislava, Qt 5.15.15, system Python
  3.13.5, Core/server 0.20.39, official MCP SDK 2.2.0, protocol 2025-06-18
- Other admitted patch/Python combinations: not measured; native CI must prove
  each deployment's actual host before it is qualified
- Portable CI passed on Python 3.10 and 3.13 for exact commit
  `8b3afd197a24eaaa17a87ad02558855976247fa9`; this does not establish which Python
  versions are supplied by every QGIS build or qualify later revisions
- Rejected/out of scope: Windows/macOS, QGIS4/Qt6, desktop attachment, external
  data providers/projects, multi-user hostile workspace isolation

## Measurable gates

| Gate | Requirement | Local evidence / remaining boundary |
|---|---|---|
| Contracts | Actual installed skill packages validate cleanly; schemas reject incomplete success/job objects | Source and wheel pytest; closed nested field/feature objects; strict async envelope or canonical result |
| Native correctness | Read back geometry, attributes, renderer/category/label state; native artifacts stay editable | Native pytest plus SDK create/edit/export/save/reopen/render workflow |
| Concurrency | Distinct concurrent callers retain arguments/results; queued timeout cannot execute later | 12 marked dispatcher calls and 8 simultaneous MCP layer creates; timeout-late-pump regression |
| Cancellation | Reject cancelled admission; roll back pre-commit edits; remove cancelled staged outputs | Token-backed native writer/edit tests plus real Core HTTP cancellation after native staging; final publication checks |
| Cancellation boundary | Do not claim preemption or rollback of an already-running native call | Still monolithic; an in-progress native commit can complete before a cancellation checkpoint. Full hard-abort/no-late-native-effect requires a different process-isolation contract |
| Input/resource safety | Closed arguments, finite JSON, 1 MiB request cap, bounded coordinates/archive size; malformed bundle rejection | Source/wheel tests include malformed manifest, duplicate keys, ZIP traversal and native geometry limits |
| Filesystem | No traversal/symlink alias, no output replacement including concurrent empty directories | Unit/native tests; files use exclusive hardlink and bundles Linux no-replace rename |
| Lifecycle | Shutdown closes real listener and registry state; cleanup is idempotent; restart uses a fresh process | Repeated source/wheel owned-process MCP smokes and native close/failed-endpoint tests |
| Build/install | Final source builds; independent wheel imports and full native workflow succeeds | `artifacts/dist`, `.wheel-venv` import origin and `artifacts/wheel-live-final` |
| CI | Portable checks automatic; native runner must be explicitly provisioned and may not silently skip | Exact commit `8b3afd197a24eaaa17a87ad02558855976247fa9` passed [CI](https://github.com/dcc-mcp/dcc-mcp-qgis/actions/runs/37100867137) and [Repository contract](https://github.com/dcc-mcp/dcc-mcp-qgis/actions/runs/37100867664). The native CI job was skipped; separate Linux acceptance is not native CI. Manual native job uses `self-hosted, Linux, qgis-3-40`. Changed revisions require fresh CI |
| Package lifecycle | Baseline install → explicit replacement → corrupt replacement preservation → uninstall/import absent → reinstall/native SDK | Standard uv rehearsal in a fresh owned environment; per-stage hashes/logs in `artifacts/package-lifecycle-final` |
| Install SOP | Complete shared plan/execute/verify/status/uninstall and rollback | Not implemented here; shared Core lifecycle review is separate. No adapter-local substitute |
| Release | Reviewed final revision, CI/provenance and publication approval | Not run or authorized by this source task |

## Operational acceptance

Use only an operator-owned workspace and a dedicated process. The endpoint is
trusted-local, not an authorization sandbox: Core's generic extension/debugging
surfaces are outside these typed-tool restrictions. The adapter rejects gateway
configuration/failover and the live smoke inspects all process-owned listeners.

After a timeout or cancellation, query the existing Core job. Do not replay a
mutation. Check whether the operation committed or published before interruption.
New-process restart discards unsaved state; saved bundles remain immutable inputs.
