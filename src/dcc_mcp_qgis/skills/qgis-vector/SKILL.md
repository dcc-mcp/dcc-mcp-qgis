---
name: qgis-vector
description: Create, query, edit and export bounded QGIS vector features.
license: MIT
metadata:
  dcc-mcp:
    dcc: qgis
    version: 0.1.0
    layer: domain
    tools: tools.yaml
    search-hint: QGIS PyQGIS GIS vector project GeoPackage GeoJSON map
    links:
      repo: https://github.com/dcc-mcp/dcc-mcp-qgis
      issues: https://github.com/dcc-mcp/dcc-mcp-qgis/issues
---

# qgis-vector

Operate only on the isolated project owned by this adapter. Host tools execute on the process main thread. Query IDs before editing. All paths are workspace-relative, and outputs never overwrite existing files. Save bundles before replacing an unsaved project. Reopening only supports adapter-created bundles, never arbitrary projects or remote sources. Geometry areas are planar CRS units, not geodesic measurements.

Start asynchronous tools once and follow Core jobs_get_status to a terminal state. After a timeout, query the same job ID rather than replaying a mutation. Cancellation cannot interrupt an indivisible QGIS native call.
