"""Revoke by non-secret credential hash; no token is read or printed."""

import argparse
import json
from pathlib import Path

from chronicle.config import atomic_json

p = argparse.ArgumentParser()
p.add_argument("--auth-file", type=Path, required=True)
p.add_argument("--revoke-sha256", required=True)
a = p.parse_args()
grants = json.loads(a.auth_file.read_text(encoding="utf-8"))
matched = 0
for grant in grants:
    if grant["sha256"] == a.revoke_sha256:
        grant["revoked"] = True
        matched += 1
if not matched:
    raise SystemExit("No matching grant; nothing changed")
atomic_json(a.auth_file, grants)
print("Credential revoked. Collector reloads grants on the next request.")
