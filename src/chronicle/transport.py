import json
import ssl
import urllib.error
import urllib.parse
import urllib.request


class TransportError(RuntimeError):
    def __init__(self, status=0, retry_after=0):
        super().__init__(f"Remote request failed (status={status})")
        self.status = status
        self.retry_after = retry_after


def require_https(url, allow_local=False):
    u = urllib.parse.urlsplit(url)
    if u.username or u.password or u.fragment or u.query:
        raise ValueError("Credentials/query/fragment forbidden in endpoint URL")
    if u.scheme != "https" and not (
        allow_local and u.scheme == "http" and u.hostname in {"127.0.0.1", "localhost", "::1"}
    ):
        raise ValueError("HTTPS required; loopback HTTP only with explicit development option")


def request(method, url, body=None, headers=None):
    data = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    h = {"Content-Type": "application/json", **(headers or {})}
    req = urllib.request.Request(url, data=data, headers=h, method=method)
    try:
        # Do not follow redirects carrying credentials.
        class NoRedirect(urllib.request.HTTPRedirectHandler):
            def redirect_request(self, *args, **kwargs):
                return None

        opener = urllib.request.build_opener(
            NoRedirect(), urllib.request.HTTPSHandler(context=ssl.create_default_context())
        )
        with opener.open(req, timeout=15) as response:
            return json.loads(response.read(4_000_000))
    except urllib.error.HTTPError as e:
        try:
            delay = float(e.headers.get("Retry-After", 0))
        except ValueError:
            delay = 0
        raise TransportError(e.code, delay) from None
    except (OSError, ValueError):
        raise TransportError() from None
