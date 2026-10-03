# dcc-mcp-qgis


**Status: hardened pre-release candidate, not a production-release claim.** This candidate pins Core/server 0.20.41 and requires native revalidation. Historical native acceptance used Linux QGIS 3.40.6, Qt 5.15.15, Python 3.13.5 and Core/server 0.20.39; those results do not qualify this upgrade. See the [runtime upgrade](docs/RUNTIME_UPGRADE_0_20_41.md) and [release gates](docs/RELEASE_READINESS.md).

Typed QGIS project and vector editing over MCP. This adapter owns a **new headless PyQGIS process** and an isolated project. It does not attach to or alter a running QGIS desktop session.

## Quick start

Use the Python supplied with QGIS. On a Linux distribution with `python3-qgis` already installed:

```sh
/usr/bin/python3 -m venv --system-site-packages .venv
.venv/bin/python -m pip install -e '.[dev]'
QT_QPA_PLATFORM=offscreen .venv/bin/dcc-mcp-qgis --workspace ./gis-work --endpoint-file ./endpoint.json
```

Runtime startup rejects QGIS outside 3.40.x, Qt6, non-Linux hosts, Python outside 3.10–3.13 and Core/server versions other than 0.20.41. Admitted version ranges are not a claim that every combination has passed native acceptance.

The default port is selected by the OS; `--port` or `DCC_MCP_QGIS_PORT` may override it. Use `mcp_url` from the endpoint file; the safe default disables the optional gateway and its registry enrollment. The endpoint is loopback-only and intended for a trusted local operator.

Load `qgis-project` and `qgis-vector` with Core `load_skill`. Query IDs before editing. All requests are limited to 1 MiB of JSON arguments; geometry coordinates to ±1e9 CRS units. All geometry is bounded, 2D WKT with an explicit EPSG CRS. Typed fields support string, integer, number, and boolean values. Tools create/query/edit vectors, export GeoJSON/GeoPackage, save/reopen editable QGZ bundles, and render PNG maps.

All GIS paths are relative to the configured workspace. Absolute paths, parent traversal, symlinks, remote sources, and output replacement are refused. Save to a **new directory**; reopening accepts adapter-created bundles only. The saved QGZ and GeoPackages can also be opened normally in QGIS Desktop.

Read [installation](install.md), [architecture](docs/ARCHITECTURE.md), and [validation](docs/VALIDATION.md). No PyPI package or GitHub release is claimed by this source tree.
