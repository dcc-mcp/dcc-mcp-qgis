# Manual installation runbook

**Pre-release manual lifecycle only.** The standard automated Install SOP
install/status/verify/uninstall/upgrade surface, receipts and host-complete
transactions remain unimplemented. This runbook is the canonical repository
installation path; it intentionally has no Install SOP conformance marker or
released artifact URL. Do not run an invented automated installer command.


## Supported configuration

This candidate requires DCC-MCP Core/Server exactly 0.20.41. Its native profile
has not been revalidated. The historical tested profile was Linux, QGIS 3.40.6,
system Python 3.13.5 and Core/Server 0.20.39; it remains historical evidence.
See the [runtime upgrade and rollback](docs/RUNTIME_UPGRADE_0_20_41.md).
QGIS is a native application dependency, not a pip dependency. Use the
interpreter that can already import `qgis.core` and `qgis.PyQt`; an unrelated
Python or Qt build is not interchangeable.

Create a dedicated virtual environment with `--system-site-packages`, install
this source package, and run the command in README.md. If an official QGIS
installation requires QGIS_PREFIX_PATH or vendor library paths, configure those
according to that installation before launch. Windows, macOS, Qt6, and QGIS 4
are rejected by the qualification gate. Other admitted QGIS3.40/Python3.10–3.13 combinations remain unverified until independently tested. Existing desktop attachment is deliberately unsupported.

## Start, status, stop, uninstall, upgrade

- Start: `dcc-mcp-qgis --workspace <root> --endpoint-file <file>`
- Status: initialize MCP at the returned URL, then call the discovered `status`
  tool. `/v1/readyz` is Core's readiness surface
- Stop: SIGINT or SIGTERM. The owned main loop drains no further work after
  shutdown begins; Core closes its endpoint, then QGIS exits
- Uninstall: stop the process and uninstall this package from its dedicated
  virtual environment. Project bundles remain user artifacts
- Upgrade: stop, install the candidate in a new dedicated environment using the
  same compatible native QGIS interpreter, rerun checks and the live smoke,
  then start a new process. Preserve the old environment and wheel for rollback

No automatic desktop plugin registration, system application modification,
Install SOP installer receipt, public wheel URL, package release or remote
service is provided. These are operator-managed source-install steps, not a
claim of full Install SOP automation.

The adapter defaults to Core `gateway_port=0` and disabled gateway failover.
Use the direct loopback MCP URL from the endpoint file. On the historical
Core 0.20.39 artifact, disabling the gateway also yielded no FileRegistry
instance ID. Endpoint-file discovery, listener behavior and shutdown need native
revalidation on 0.20.41. External gateway enrollment and network exposure are
not validated or enabled by this adapter.

Paths in domain tools are workspace-relative. The endpoint file is an
operator-selected CLI output. Choose a new evidence directory and endpoint filename for every smoke; endpoint files never overwrite. Restart using a new process, not the stopped server object.

If the native interpreter lacks ensurepip, use an already-installed `uv` to create
the isolated environment and install dependencies without changing system Python:

```sh
uv venv --python /usr/bin/python3 --system-site-packages .venv
uv pip install --python .venv/bin/python -e '.[dev]'
uv build --python /usr/bin/python3
```


## Standard package lifecycle acceptance

Run the opt-in `scripts/package_lifecycle.py` with a local baseline wheel, final
wheel, new output directory and native Python. It creates its own environment,
never touches the host installation or existing environments, and performs
install/replace/corrupt-replacement/uninstall/reinstall followed by real native
and MCP checks. This rehearsal is separate from Core's automated Install SOP.
