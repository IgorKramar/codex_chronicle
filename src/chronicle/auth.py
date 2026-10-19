"""Revocable scoped grants. No token values are persisted or logged."""

import datetime as dt
import hashlib
import hmac
import json
import re
from pathlib import Path


class AuthRegistry:
    def __init__(self, grants=None, path=None):
        self.fixed = grants
        self.path = Path(path) if path else None
        self.read()  # Invalid startup configuration is a failure, never anonymous access.

    def read(self):
        grants = json.loads(self.path.read_text(encoding="utf-8")) if self.path else self.fixed
        if not isinstance(grants, list) or not grants:
            raise ValueError("Explicit hashed grants required")
        for g in grants:
            if (
                not isinstance(g, dict)
                or not isinstance(g.get("sha256"), str)
                or not re.fullmatch(r"[a-f0-9]{64}", g["sha256"])
            ):
                raise ValueError("Invalid credential hash")
            if not isinstance(g.get("scopes"), list) or not all(
                isinstance(x, str) for x in g["scopes"]
            ):
                raise ValueError("Scopes must be an explicit list")
            if not isinstance(g.get("projects"), list) or not all(
                isinstance(x, str) for x in g["projects"]
            ):
                raise ValueError("Projects must be an explicit list")
        return grants

    def authenticate(self, token):
        digest = hashlib.sha256(token.encode()).hexdigest()
        for g in self.read():
            if not hmac.compare_digest(g["sha256"], digest) or g.get("revoked", False):
                continue
            if g.get("expires_at"):
                expiration = dt.datetime.fromisoformat(g["expires_at"])
                if expiration.tzinfo is None or expiration <= dt.datetime.now(dt.UTC):
                    continue
            return g
        return None


def principal_id(grant):
    return grant.get("principal_id") or grant.get("computer_id") or grant["sha256"]
