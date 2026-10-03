# Architecture and boundaries

`QgisMcpServer` is a composition root using `DccServerBase`,
`DccServerOptions.from_env`, and `HostExecutionBridge`. Core owns HTTP/MCP,
manifest discovery, progressive skill loading, job state and native queues.
`QgisDispatcher` adds only owner-thread enforcement and the host wake hook to
`HostUiDispatcherBase`. The CLI pumps its queue and Qt events on the process
main thread. HTTP workers never call PyQGIS. A defense-in-depth main-thread
check precedes every skill's access to the owned session.
Dispatcher construction and queue drains, and server construction, startup,
pumping and shutdown independently enforce the process main thread. The server
also checks session ownership before allocating Core state or touching Qt.

The service and QGIS have the same process lifetime. It is a standalone
headless instance with no external host PID. A new QgsApplication and a private
QgsProject are created; an existing Qt/QGIS application is rejected. No GUI
process, singleton desktop project, or user scene is modified.

## Domain workflow

- `qgis-project`: status/capabilities, project query/new, save/reopen, PNG render
- `qgis-vector`: layer creation, bounded feature query/add/edit, export and style

All scripts expose typed `main` entry points, retain lazy host imports, and use
Core skill success/error helpers. Mutation success includes readback evidence.
Host tools are `affinity: main`; the pure capability description is `any`.
Add batches, save/reopen, render and vector export use Core asynchronous jobs.
The operations are monolithic; cancellation checkpoints guard admission, edit-buffer commit, project replacement and artifact publication. Cancellation after a native writer returns removes its staging files; it does not publish a final artifact. A cancelled pre-commit feature edit rolls back its buffer. These checkpoints cannot interrupt a native writer/render/commit call already in progress or undo a commit that wins a cancellation race.
Query the existing Core job after timeout. Do not replay a mutation.

Memory vector layers support 2D Point/LineString/Polygon, 32 layers, 32 fields,
1000 features per batch, 10000 per layer, 100 per query, and 2048px PNG outputs.
Coordinates and numeric attributes must be finite. Polygon validity is checked
by GEOS. Geometry area is planar in layer CRS units, never a geodesic or
scientific inference. No raw Python tool is added by this adapter. Core may
expose its own diagnostic/dynamic extension surfaces, so this is a trusted-local
MCP endpoint, not an untrusted-code sandbox or a tool authorization boundary.

## Persistence and style

Save serializes memory layers to separate GeoPackages and writes a QGZ plus a
hash manifest in a new bundle directory. Renderer, labels and layer order are
cloned. Reopen verifies artifact hashes and local OGR sources before loading;
data is materialized back into memory so editing never mutates a saved bundle.
Field IDs/layer IDs can change across reopen, so clients query them again. Inserted feature sets and exported/reopened layers are verified using all user attributes and native WKB geometry, rather than counts alone; renderer symbols, categories and label properties are compared after styling.
Export uses exclusive hardlink publication and refuses an existing target.
The bundle directory is staged, hash/XML-validated and published through Linux `renameat2(RENAME_NOREPLACE)` only after successful writes. An existing empty directory is preserved even if it appears immediately before publication;
concurrent external modifications to the workspace are unsupported.

All requested paths reject absolute paths, traversal and existing symlinks.
The workspace and its files must be trusted and exclusively operator-managed.
Checksums detect changes, not authenticate producers. This adapter does not
claim hostile QGIS project safety; do not place untrusted bundles in its
workspace. Arbitrary projects, remote providers, plugin macros, raster,
processing algorithms, and GUI automation are outside the supported workflow.

## Compatibility

Python floor is 3.10 for this host-specific adapter. Core and server are pinned
to 0.20.41 for this upgrade candidate. Runtime qualification precedes
QgsApplication allocation and returns actual host/Qt/Python/Core versions through
`status`. Linux/QGIS3.40.x/Qt5/Python3.10–3.13 remain the admitted API family.
The historical measured matrix used Core/server 0.20.39 and does not qualify
0.20.41; the [upgrade record](RUNTIME_UPGRADE_0_20_41.md) tracks that boundary.
`supported_profile` retains the historical `validated_qgis` label together with
its explicit `native_acceptance_profile`, and marks the current runtime native
verification false. Historical native evidence and portability gaps are recorded
in VALIDATION.md. CI has no release or credential-writing jobs.

## Stop and restart contract

Public Python host operations independently enforce main-thread ownership, finite
JSON arguments, aggregate size limits and the open-session state. Direct queue
timeouts explicitly cancel their original Core request ID so a callback still
waiting in the queue cannot mutate when pumped later. Core still owns native HTTP
request queues and job lifetimes.

`stop()` closes the dispatcher before stopping the Core server; both `stop()` and
owned-session `close()` tolerate repeated shutdown. CLI cleanup always closes
QGIS even if server shutdown raises. Reusing a stopped server is rejected.
Restart means a fresh owned process and a new endpoint/instance, with no implicit
mutation replay or unsaved-state recovery. Endpoint JSON uses exclusive creation
and never overwrites an operator file.
