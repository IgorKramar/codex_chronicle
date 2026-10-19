import json
import sys
import tempfile
import unittest

from chronicle.install import prepare_marketplace


class LocalInstallTest(unittest.TestCase):
    def test_legacy_manifest_keeps_hooks_discoverable(self):
        with tempfile.TemporaryDirectory() as home:
            root = prepare_marketplace({"home": home})
            plugin = root / "plugins" / "codex-chronicle"
            self.assertFalse((plugin / "plugin.json").exists())
            manifest = json.loads((plugin / ".codex-plugin" / "plugin.json").read_text())
            hooks = json.loads((plugin / manifest["hooks"]).read_text())
            command = hooks["hooks"]["SessionStart"][0]["hooks"][0]["command"]
            self.assertIn(sys.executable, command)


if __name__ == "__main__":
    unittest.main()
