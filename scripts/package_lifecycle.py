"""Rehearse standard uv install/replace/uninstall in a NEW isolated environment.

This operator-run acceptance script is not an adapter runtime installer and does
not implement or claim Core's Install SOP transaction/receipt contract.
"""

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

SNAPSHOT = """
import hashlib, importlib.metadata, json
from pathlib import Path
import dcc_mcp_qgis
root = Path(dcc_mcp_qgis.__file__).parent
print(json.dumps({'origin': str(root), 'version': importlib.metadata.version('dcc-mcp-qgis'),
 'files': {str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(root.rglob('*')) if p.is_file() and '__pycache__' not in p.parts}}))
"""


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable)
    parser.add_argument("--baseline-wheel", type=Path, required=True)
    parser.add_argument("--final-wheel", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    output = args.output.resolve()
    output.mkdir(parents=True, exist_ok=False)
    clean = output / "clean"
    clean.mkdir()
    baseline, final = args.baseline_wheel.resolve(strict=True), args.final_wheel.resolve(strict=True)
    uv = shutil.which("uv")
    if uv is None:
        raise RuntimeError("Use an already-installed official uv; this script does not install tooling")
    env = {key: value for key, value in os.environ.items() if key not in {"PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"}}
    env.update({"UV_CACHE_DIR": str(output / "cache"), "UV_LINK_MODE": "copy", "QT_QPA_PLATFORM": "offscreen"})
    stages = []

    def run(name, command, *, succeeds=True):
        result = subprocess.run(
            [str(item) for item in command], cwd=clean, env=env, capture_output=True, text=True, timeout=180
        )
        (output / (name + ".log")).write_text(result.stdout + result.stderr)
        stages.append({"stage": name, "exit_code": result.returncode, "expected_success": succeeds})
        if (result.returncode == 0) is not succeeds:
            raise AssertionError(f"{name} unexpected exit status; inspect its log")
        return result.stdout

    python = output / "venv/bin/python"
    run("create-environment", [uv, "venv", "--python", args.python, "--system-site-packages", output / "venv"])
    run(
        "baseline-install",
        [uv, "pip", "install", "--python", python, baseline, "-r", root / "docs/requirements-validation.txt"],
    )
    first = json.loads(run("baseline-origin", [python, "-c", SNAPSHOT]))
    assert str(output / "venv") in first["origin"]
    run("upgrade", [uv, "pip", "install", "--python", python, "--reinstall-package", "dcc-mcp-qgis", final])
    upgraded = json.loads(run("upgrade-origin", [python, "-c", SNAPSHOT]))
    expected = {
        str(path.relative_to(root / "src/dcc_mcp_qgis")): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((root / "src/dcc_mcp_qgis").rglob("*"))
        if path.is_file() and "__pycache__" not in path.parts
    }
    assert upgraded["files"] == expected, "Installed wheel content differs from final source"
    assert upgraded["version"] == first["version"] == "0.1.0"
    assert upgraded["files"] != first["files"], "Baseline and upgraded source must differ"
    corrupt = output / "corrupt" / final.name
    corrupt.parent.mkdir()
    corrupt.write_bytes(b"Deliberately invalid wheel for replacement failure acceptance")
    run(
        "corrupt-upgrade",
        [uv, "pip", "install", "--python", python, "--reinstall-package", "dcc-mcp-qgis", corrupt],
        succeeds=False,
    )
    after_failure = json.loads(run("post-failure-origin", [python, "-c", SNAPSHOT]))
    assert after_failure == upgraded, "Failed package preparation altered installed working files"
    run("uninstall", [uv, "pip", "uninstall", "--python", python, "dcc-mcp-qgis"])
    run(
        "uninstall-verify",
        [python, "-c", "import importlib.util; assert importlib.util.find_spec('dcc_mcp_qgis') is None"],
    )
    run("reinstall", [uv, "pip", "install", "--python", python, final])
    reinstalled = json.loads(run("reinstall-origin", [python, "-c", SNAPSHOT]))
    assert reinstalled == upgraded
    env["DCC_MCP_QGIS_REQUIRE_NATIVE"] = "1"
    run("native-suite", [python, "-m", "pytest", "-q", root / "tests"])
    run("native-mcp", [python, root / "scripts/live_smoke.py", "--output", output / "live-mcp"])
    evidence = {
        "status": "PASS",
        "scope": "standard package lifecycle; not automated Core Install SOP",
        "baseline_sha256": hashlib.sha256(baseline.read_bytes()).hexdigest(),
        "final_sha256": hashlib.sha256(final.read_bytes()).hexdigest(),
        "baseline": first,
        "final": reinstalled,
        "failed_replacement_preserved_files": True,
        "uninstalled_import_unavailable": True,
        "stages": stages,
    }
    (output / "result.json").write_text(json.dumps(evidence, indent=2) + "\n")
    print(json.dumps({key: value for key, value in evidence.items() if key not in {"baseline", "final", "stages"}}))


if __name__ == "__main__":
    main()
