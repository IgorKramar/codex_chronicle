"""Clean-venv smoke for the core wheel and the standalone contracts wheel."""

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    with tempfile.TemporaryDirectory(prefix="fip-package-") as tmp:
        tmp = Path(tmp)

        def environment(name):
            target = tmp / name
            subprocess.run(
                [sys.executable, "-m", "venv", str(target)], check=True, capture_output=True
            )
            return target / ("Scripts/python.exe" if os.name == "nt" else "bin/python")

        core = environment("core")
        wheel = ROOT / "dist/codex_chronicle-0.2.0-py3-none-any.whl"
        contracts = ROOT / "dist/fip_contracts-1.0.0-py3-none-any.whl"
        subprocess.run(
            [str(core), "-m", "pip", "install", "--no-deps", str(wheel)],
            check=True,
            capture_output=True,
        )
        subprocess.run(
            [
                str(core),
                "-c",
                "import importlib.util; assert importlib.util.find_spec('jsonschema') is None; assert importlib.util.find_spec('mcp') is None",
            ],
            check=True,
            capture_output=True,
        )
        env = {**os.environ, "CHRONICLE_HOME": str(tmp / "home")}
        for args in [["init"], ["install", "--prepare-only"], ["status"]]:
            result = subprocess.run(
                [str(core), "-m", "chronicle.cli", *args], env=env, check=True, capture_output=True
            )
            assert json.loads(result.stdout)
        standalone = environment("contracts")
        subprocess.run(
            [str(standalone), "-m", "pip", "install", str(contracts)],
            check=True,
            capture_output=True,
        )
        code = """
import json, sys
from importlib.resources import files
from fip_contracts import validate, schema
sample=json.loads(files('fip_contracts').joinpath('examples/v1/bootstrap.http-body.json').read_text())
validate('AgentEvent',sample)
assert 'chronicle' not in sys.modules
assert schema()['$id']=='urn:fip:v1'
"""
        subprocess.run([str(standalone), "-c", code], cwd=tmp, check=True, capture_output=True)
        subprocess.run(
            [
                sys.executable,
                "-c",
                "import sys; from chronicle.memory_service import MemoryService; assert 'fastapi' not in sys.modules; assert 'mcp' not in sys.modules; assert 'chronicle.notion' not in sys.modules",
            ],
            check=True,
            capture_output=True,
        )
        result = {
            "core_wheel_without_server_dependencies": "passed",
            "core_init_prepare_install_status": "passed",
            "standalone_fip_contracts_without_chronicle": "passed",
            "bundled_schemas_and_examples": "passed",
            "memory_core_without_http_mcp_notion_imports": "passed",
            "version": "0.2.0",
            "contract_version": "1.0.0",
        }
        (ROOT / "evidence/fip-package-probe.json").write_text(json.dumps(result, indent=2) + "\n")
        print(json.dumps(result))


if __name__ == "__main__":
    main()
