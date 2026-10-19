import re
from pathlib import Path

SENSITIVE_KEY = re.compile(
    r"(?i)(password|passwd|secret|token|authorization|api.?key|credential|private.?key)"
)
PATTERNS = [
    re.compile(
        r"-----BEGIN (?:[A-Z]+ )?PRIVATE KEY-----[\s\S]*?(?:-----END (?:[A-Z]+ )?PRIVATE KEY-----|$)"
    ),
    re.compile(r"(?i)\b(?:sk|ghp|github_pat|ntn|secret)[-_][A-Za-z0-9_-]{12,}"),
    re.compile(r"(?i)\b(?:Bearer|Basic)\s+[A-Za-z0-9._~+/=-]+"),
    re.compile(r"(?i)\b(?:password|passwd|token|api[_-]?key|secret)\s*[:=]\s*[^\s,;]+"),
    re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"),
    re.compile(r"(?i)(https?://)[^/\s@]+@"),
    re.compile(r"\bAKIA[A-Z0-9]{16}\b"),
]


def redact(value):
    if isinstance(value, dict):
        return {
            str(k): "[REDACTED]" if SENSITIVE_KEY.search(str(k)) else redact(v)
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [redact(v) for v in value[:1000]]
    if isinstance(value, str):
        for pattern in PATTERNS:
            value = pattern.sub("[REDACTED]", value)
        return value[:16000]
    return value


def excluded(cwd, cfg):
    p = Path(cwd).resolve()
    return any(p == Path(x).resolve() or Path(x).resolve() in p.parents for x in cfg["exclude"])


def safe_path(path):
    parts = Path(path).parts
    return not any(
        x.lower() in {".env", ".ssh", ".aws", ".npmrc", "credentials", "id_rsa", "id_ed25519"}
        or x.lower().startswith(".env.")
        or x.lower().endswith((".pem", ".key"))
        for x in parts
    )
