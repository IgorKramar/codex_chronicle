"""Stateful contract mock for the Notion endpoints Chronicle actually uses."""

import uuid
from copy import deepcopy

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class MockNotion:
    def __init__(self):
        self.pages = {}
        self.blocks = {"parent": []}
        self.databases = {}
        self.sources = {}
        self.calls = []
        self.fail_after_create = False
        self.rate_limit = False
        self.parent = "parent"
        self.app = FastAPI()

        @self.app.api_route("/v1/{path:path}", methods=["GET", "POST", "PATCH"])
        async def api(path: str, request: Request):
            if request.headers.get("authorization") != "Bearer test-notion":
                return JSONResponse({"code": "unauthorized"}, status_code=401)
            if request.headers.get("notion-version") != "2026-03-11":
                return JSONResponse({"code": "invalid_request"}, status_code=400)
            body = await request.json() if request.method != "GET" else {}
            self.calls.append((request.method, path, deepcopy(body)))
            if self.rate_limit:
                self.rate_limit = False
                return JSONResponse(
                    {"code": "rate_limited"}, status_code=429, headers={"Retry-After": "120"}
                )
            parts = path.split("/")
            if parts[0] == "blocks" and len(parts) == 3 and parts[2] == "children":
                return {
                    "results": self.blocks.get(parts[1], []),
                    "has_more": False,
                    "next_cursor": None,
                }
            if path == "databases" and request.method == "POST":
                assert "initial_data_source" in body and "properties" not in body
                did, sid = str(uuid.uuid4()), str(uuid.uuid4())
                self.databases[did] = {"id": did, "data_sources": [{"id": sid}]}
                self.sources[sid] = {
                    "properties": body["initial_data_source"]["properties"],
                    "pages": [],
                }
                title = "".join(x["text"]["content"] for x in body["title"])
                self.blocks[body["parent"]["page_id"]].append(
                    {"id": did, "type": "child_database", "child_database": {"title": title}}
                )
                return self.databases[did]
            if parts[0] == "databases" and request.method == "GET":
                return self.databases[parts[1]]
            if parts[0] == "data_sources" and parts[-1] == "query":
                candidates = [
                    self.pages[pid]
                    for pid in self.sources[parts[1]]["pages"]
                    if not self.pages[pid].get("in_trash")
                ]
                if "filter" in body:
                    f = body["filter"]
                    candidates = [
                        p
                        for p in candidates
                        if "".join(
                            x["text"]["content"]
                            for x in p["properties"][f["property"]]["rich_text"]
                        )
                        == f["rich_text"]["equals"]
                    ]
                return {"results": candidates, "has_more": False}
            if path == "pages" and request.method == "POST":
                pid = str(uuid.uuid4())
                page = {
                    "id": pid,
                    "url": "https://notion.example/" + pid,
                    "properties": body["properties"],
                }
                self.pages[pid] = page
                self.blocks[pid] = []
                for block in body.get("children", []):
                    for rt in block["paragraph"]["rich_text"]:
                        assert len(rt["text"]["content"]) <= 2000
                    self.blocks[pid].append({**block, "id": str(uuid.uuid4())})
                parent = body["parent"]
                if parent["type"] == "data_source_id":
                    source = self.sources[parent["data_source_id"]]
                    assert set(body["properties"]) <= set(source["properties"])
                    source["pages"].append(pid)
                else:
                    title = "".join(
                        x["text"]["content"] for x in body["properties"]["title"]["title"]
                    )
                    self.blocks[parent["page_id"]].append(
                        {"id": pid, "type": "child_page", "child_page": {"title": title}}
                    )
                if self.fail_after_create:
                    self.fail_after_create = False
                    return JSONResponse({"code": "service_unavailable"}, status_code=503)
                return page
            if parts[0] == "pages" and request.method == "PATCH":
                page = self.pages[parts[1]]
                page["properties"].update(body.get("properties", {}))
                if "in_trash" in body:
                    page["in_trash"] = body["in_trash"]
                return page
            if parts[0] == "blocks" and request.method == "PATCH":
                for blocks in self.blocks.values():
                    for block in blocks:
                        if block["id"] == parts[1]:
                            block.update(body)
                            return block
            return JSONResponse({"code": "object_not_found", "path": path}, status_code=404)
