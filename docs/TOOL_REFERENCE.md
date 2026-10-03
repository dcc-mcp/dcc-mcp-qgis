# Typed workflow reference

Discover with `search_skills(query="qgis")`, then `load_skill(skill_name="qgis-vector")`.
Follow `tools/list` pagination. In the historical Core 0.20.39 smoke, the load result reported canonical
`qgis_vector__*` slugs while `tools/list` can publish their bare local names;
both resolve, but use the listed name so SDK result-schema validation applies.
Repeat discovery and SDK schema checks on the 0.20.41 candidate before native
acceptance; historical discovery results are not carried forward.

Project tools are initially loaded:

- `status()` returns actual QGIS, Qt, Python, Core/server versions and limits
- `get_capabilities()` is pure metadata and can run off the host thread
- `inspect_project(limit=25)` reports layer IDs, names, CRS, field schema,
  feature count, renderer type and label enablement
- `new_project(title="Untitled", crs="EPSG:3857", discard_changes=False)`
- `save_project(directory)` writes a new directory containing project.qgz,
  layer GeoPackages and an integrity manifest
- `reopen_project(path, discard_changes=False)` opens a saved bundle into
  editable memory layers. Query IDs again
- `render_map(path, width=800, height=600)` renders the current ordered layers
  with an automatic extent and white background

Vector skill tools:

- `create_layer(name, geometry_type, crs="EPSG:3857", fields=[])`
  Fields are objects with name and type; types: string, integer, number, boolean
- `add_features(layer_id, features)` takes `{wkt, attributes}` feature objects
- `query_features(layer_id, limit=25, offset=0)` returns IDs, typed attributes,
  WKT and planar area
- `update_feature(layer_id, feature_id, attributes=None, wkt=None)` requires
  at least one of attributes or WKT
- `style_layer(layer_id, color, outline_color, opacity, width, size,
  category_field, categories, label_field, label_size, label_color)` applies
  bounded styling. Categories are `{value: string, color: "#RRGGBB"}`;
  labels use a literal existing field, not an expression. Omitted label_field
  disables labels. Width and marker size use QGIS symbol millimeters
- `export_layer(layer_id, path, format="GeoJSON")` supports GeoJSON/GPKG

Create bottom layers first; new layers are inserted above earlier layers.
Renderer/labels/draw order survive native save and reopen. New-project CRS
sets the map CRS; each layer also declares its data CRS. There is no raster,
network source, arbitrary project import, expression, or processing tool.

For asynchronous calls, record the returned job_id and poll Core
`jobs_get_status(job_id)` until completed/failed/cancelled/interrupted. The
terminal domain result has canonical success/message/error/context fields.
Core's initial job envelope is a different shape; async output schemas do not
require domain success fields on that initial response. Never treat the
initial pending response as completed work or automatically replay it.

Every operation accepts at most 1 MiB of aggregate JSON arguments, independently
of per-field limits. Coordinates must be finite and within ±1e9 CRS units.
Malformed nested feature/field objects, duplicate style categories, non-boolean
discard flags and stale layer IDs fail before mutation. Bundle input is bounded
to 128 MiB total, with at most four ZIP members and 16 MiB total uncompressed ZIP
content. These are resource bounds, not a security sandbox for hostile native
parsers or concurrent filesystem attackers.

### Typed label presentation

`style_layer` accepts `label_buffer_size` from 0 to 2 millimeters (default 0.7;
0 disables the halo), `label_buffer_color` as six-digit RGB hex, `font_family`
as an exact already-installed local family name, and boolean `label_bold`.
No font is downloaded or installed. These properties are part of style readback
and native project save/reopen validation.

Numeric fields accept finite floating-point values and safe JSON integers.
Integers provided to a `number` field are normalized to native Double before
commit and verification; semantic numeric equality is preserved across GeoJSON.
