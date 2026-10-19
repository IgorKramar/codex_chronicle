import os
import shutil
import subprocess
import sys
from pathlib import Path

from .config import atomic_json
from .events import HOOKS


def bundle_path():
    packaged = Path(__file__).parent / "assets" / "plugin"
    return packaged if packaged.exists() else Path(__file__).parents[2] / "plugin"


def prepare_marketplace(cfg):
    root = Path(cfg["home"]) / "marketplace"
    target = root / "plugins" / "codex-chronicle"
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(bundle_path(), target)
    command = '"' + sys.executable + '" -m chronicle.hook'
    definitions = {
        e: [
            {
                "hooks": [
                    {
                        "type": "command",
                        "command": command,
                        "commandWindows": command if os.name == "nt" else "py -3 -m chronicle.hook",
                        "timeout": 3,
                    }
                ]
            }
        ]
        for e in HOOKS
    }
    atomic_json(
        target / "hooks" / "hooks.json",
        {"description": "Chronicle durable capture", "hooks": definitions},
    )
    atomic_json(
        root / ".agents" / "plugins" / "marketplace.json",
        {
            "name": "chronicle-local",
            "interface": {"displayName": "Codex Chronicle"},
            "plugins": [
                {
                    "name": "codex-chronicle",
                    "source": {"source": "local", "path": "./plugins/codex-chronicle"},
                    "policy": {"installation": "AVAILABLE", "authentication": "ON_INSTALL"},
                    "category": "Productivity",
                }
            ],
        },
    )
    return root


def install(cfg, prepare_only=False):
    root = prepare_marketplace(cfg)
    if not prepare_only:
        for args in [
            ["codex", "plugin", "marketplace", "add", str(root), "--json"],
            ["codex", "plugin", "add", "codex-chronicle@chronicle-local", "--json"],
        ]:
            subprocess.run(args, check=True, timeout=60, stdout=subprocess.DEVNULL)
    return {
        "marketplace": str(root),
        "prepared_only": prepare_only,
        "next": "Проверьте и разрешите hooks в Codex. Запустите chronicle agent или установите службу по docs/OPERATIONS.md.",
    }


def uninstall():
    subprocess.run(
        ["codex", "plugin", "remove", "codex-chronicle@chronicle-local", "--json"],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
    )
    subprocess.run(
        ["codex", "plugin", "marketplace", "remove", "chronicle-local", "--json"],
        check=True,
        timeout=60,
        stdout=subprocess.DEVNULL,
    )
    return {
        "removed": True,
        "data": "Локальные данные сохранены. Для удаления используйте chronicle purge.",
    }
