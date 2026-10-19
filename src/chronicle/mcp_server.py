"""Official MCP SDK stdio server. No listener, model calls or database access."""

import asyncio
import json
import os

from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolResult, TextContent, Tool, ToolAnnotations

from .contracts import OPERATIONS, embedded
from .fip_client import FipClient
from .memory_service import WRITE_TYPES, ApiFault, error_response

DESCRIPTIONS = {
    "get_recent_activity": "Read recent events newest first, with snapshot pagination and scope filters.",
    "get_daily_summary": "Read bounded UTC daily event summary with counts, source events and pagination; counts are not completed tasks.",
    "register_test_result": "Append a test result revision with evidence; Passed requires completed execution and exit code zero.",
    "register_knowledge": "Append a knowledge revision with primary sources; verified requires verify scope.",
    "list_projects": "List authorized projects with compact context; paginated.",
    "get_project_state": "Get source-backed project context and a bounded LLM summary.",
    "get_project_history": "Read immutable project events with category, author, session and time filters.",
    "list_sessions": "List sessions filtered by project, agent, time and status.",
    "get_session_details": "Resolve one session; use project history and evidence references for detailed activity.",
    "search_knowledge": "Literal Unicode casefold substring AND search; no semantic search or ranking.",
    "get_decisions": "Read decision revisions, including Proposed, Rejected and Superseded records.",
    "get_failures": "Read failed experiments and failure events with primary sources.",
    "get_artifacts": "List artifact links; does not download or execute artifact content.",
    "get_test_results": "Read test outcomes, execution status, provenance and evidence.",
    "append_event": "Persist an immutable external event and optional knowledge/test/context records. Requires idempotency_key.",
    "register_decision": "Append a decision revision; Accepted needs decide scope. Requires idempotency_key.",
    "register_artifact": "Register an artifact URI and evidence; no file upload. Requires idempotency_key.",
    "get_capabilities": "Discover FIP v1 operations, version, search semantics and size limits.",
}


def create_server(client, writes=False):
    server = Server("chronicler-fip-v1")

    @server.list_tools()
    async def list_tools():
        return [
            Tool(
                name=op,
                description=DESCRIPTIONS[op],
                inputSchema=embedded(op + "Arguments"),
                outputSchema=embedded(op + "ToolResult"),
                annotations=ToolAnnotations(
                    readOnlyHint=op not in WRITE_TYPES,
                    destructiveHint=False,
                    idempotentHint=True,
                    openWorldHint=True,
                ),
            )
            for op in OPERATIONS
            if writes or op not in WRITE_TYPES
        ]

    @server.call_tool(validate_input=False)
    async def call_tool(name, arguments):
        try:
            if name not in OPERATIONS or name in WRITE_TYPES and not writes:
                raise ApiFault("forbidden", "Tool is not enabled for this MCP server", 403)
            result = await asyncio.to_thread(client.call, name, arguments or {})
            return CallToolResult(
                content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
                structuredContent=result,
                isError=False,
            )
        except ApiFault as exc:
            result = error_response(exc)
        except Exception:
            # No raw remote errors, request payloads, tokens or tracebacks on protocol stdout.
            result = error_response(
                ApiFault("client_error", "MCP request failed; check local configuration", 422)
            )
        return CallToolResult(
            content=[TextContent(type="text", text=json.dumps(result, ensure_ascii=False))],
            structuredContent=result,
            isError=True,
        )

    return server


async def run():
    client = FipClient(
        os.environ.get("CHRONICLE_API_URL", "https://localhost:8787"),
        os.environ.get("CHRONICLE_API_TOKEN", os.environ.get("CHRONICLE_READ_TOKEN", "")),
        os.environ.get("CHRONICLE_FIP_OUTBOX"),
        os.environ.get("CHRONICLE_CLIENT_ID"),
        os.environ.get("CHRONICLE_ALLOW_LOOPBACK_HTTP") == "1",
    )
    writes_enabled = os.environ.get("CHRONICLE_MCP_WRITE_ENABLED") == "1"
    server = create_server(client, writes_enabled)
    stop = asyncio.Event()

    async def retry_loop():
        while not stop.is_set():
            await asyncio.to_thread(client.flush)
            try:
                await asyncio.wait_for(stop.wait(), timeout=60)
            except TimeoutError:
                pass

    task = asyncio.create_task(retry_loop()) if writes_enabled else None
    try:
        async with stdio_server() as (read, write):
            await server.run(read, write, server.create_initialization_options())
    finally:
        stop.set()
        if task is not None:
            await task


def main():
    asyncio.run(run())


if __name__ == "__main__":
    main()
