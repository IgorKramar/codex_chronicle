"""Offline provisioning. Tokens go only to a new private credential file."""

import argparse
import datetime as dt
import hashlib
import json
import os
import secrets
from pathlib import Path

from chronicle.config import atomic_json

p = argparse.ArgumentParser()
p.add_argument("--auth-file", type=Path, required=True)
p.add_argument("--credential-file", type=Path, required=True)
p.add_argument("--computer")
p.add_argument("--project", action="append", required=True)
p.add_argument("--read-only", action="store_true")
p.add_argument("--fip", action="store_true")
p.add_argument("--principal")
p.add_argument("--agent")
p.add_argument("--allow-content", action="store_true")
p.add_argument(
    "--scope", choices=["read", "write", "decide", "verify", "revise", "observe"], action="append"
)
p.add_argument("--expires-at")
a = p.parse_args()
if a.fip:
    if not a.principal or not a.agent or not a.read_only and not a.allow_content:
        p.error("FIP needs --principal, --agent and explicit --allow-content for writes")
elif not a.read_only and not a.computer:
    p.error("--computer required for Codex write grants")
if a.expires_at:
    expiration = dt.datetime.fromisoformat(a.expires_at)
    if expiration.tzinfo is None or expiration <= dt.datetime.now(dt.UTC):
        p.error("--expires-at must be an aware future timestamp")
token = secrets.token_urlsafe(48)
grants = json.loads(a.auth_file.read_text()) if a.auth_file.exists() else []
grant = {
    "sha256": hashlib.sha256(token.encode()).hexdigest(),
    "scopes": ["read"] if a.read_only else a.scope or (["read", "write"] if a.fip else ["write"]),
    "computer_id": a.computer,
    "projects": a.project,
}
if a.fip:
    grant.update(principal_id=a.principal, agent_id=a.agent, allow_content=a.allow_content)
if a.expires_at:
    grant["expires_at"] = expiration.astimezone(dt.UTC).isoformat()
grants.append(grant)
a.auth_file.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
fd = os.open(a.credential_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
variable = (
    "CHRONICLE_API_TOKEN"
    if a.fip
    else "CHRONICLE_READ_TOKEN"
    if a.read_only
    else "CHRONICLE_WRITE_TOKEN"
)
with os.fdopen(fd, "w") as f:
    f.write(variable + "=" + token + "\n")
atomic_json(a.auth_file, grants)
print("Created scoped grant and private credential file. Transfer via a secure channel.")
