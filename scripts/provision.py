"""Offline provisioning. Prints no tokens; writes private files for secure delivery."""

import argparse
import hashlib
import json
import os
import secrets
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--auth-file", type=Path, required=True)
p.add_argument("--credential-file", type=Path, required=True)
p.add_argument("--computer")
p.add_argument("--project", action="append", required=True)
p.add_argument("--read-only", action="store_true")
a = p.parse_args()
if not a.read_only and not a.computer:
    p.error("--computer required for write grants")
token = secrets.token_urlsafe(48)
grants = json.loads(a.auth_file.read_text()) if a.auth_file.exists() else []
grants.append(
    {
        "sha256": hashlib.sha256(token.encode()).hexdigest(),
        "scopes": ["read"] if a.read_only else ["write"],
        "computer_id": a.computer,
        "projects": a.project,
    }
)
a.auth_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(a.credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
with os.fdopen(fd, "w") as f:
    f.write(
        ("CHRONICLE_READ_TOKEN" if a.read_only else "CHRONICLE_WRITE_TOKEN") + "=" + token + "\n"
    )
fd = os.open(a.auth_file, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
with os.fdopen(fd, "w") as f:
    json.dump(grants, f, indent=2)
print("Created scoped grant and private credential file. Transfer via a secure channel.")
