import os
from pathlib import Path
from urllib.parse import quote

import uvicorn

from chronicle.collector import create_app

password = Path("/run/secrets/postgres_password").read_text().strip()
os.environ["CHRONICLE_DATABASE"] = (
    "postgresql://chronicle:" + quote(password, safe="") + "@postgres/chronicle"
)
notion = Path("/run/secrets/notion_token").read_text().strip()
if notion:
    os.environ["NOTION_TOKEN"] = notion
uvicorn.run(create_app(), host="0.0.0.0", port=8787, log_config=None, proxy_headers=False)
