"""HTTP adapter for the same domain operations used by MCP clients."""

import asyncio
import json
import re
import uuid

from fastapi import Depends, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException

from .contracts import BUNDLE, OPERATIONS, validate
from .fip_routes import ROUTES
from .memory_service import WRITE_TYPES, ApiFault, MemoryService, envelope, error_response


def is_fip(request):
    return request.url.path.startswith("/v1/memory") or request.url.path == "/v1/capabilities"


def request_id(request):
    value = request.headers.get("X-Request-ID", "")
    return value if re.fullmatch(r"[A-Za-z0-9_.:@/-]{1,256}", value) else str(uuid.uuid4())


def attach(app, store, auth):
    service = MemoryService(store)
    app.state.memory = service

    @app.exception_handler(ApiFault)
    async def fault(request, exc):
        return JSONResponse(error_response(exc, request_id(request)), status_code=exc.status)

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        if is_fip(request):
            code = {
                401: "unauthorized",
                403: "forbidden",
                404: "not_found",
                503: "auth_unavailable",
            }.get(exc.status_code, "http_error")
            return JSONResponse(
                error_response(
                    ApiFault(code, "Request denied", exc.status_code), request_id(request)
                ),
                status_code=exc.status_code,
                headers=exc.headers,
            )
        return JSONResponse(
            {"detail": exc.detail}, status_code=exc.status_code, headers=exc.headers
        )

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        if is_fip(request):
            return JSONResponse(
                error_response(
                    ApiFault("invalid_request", "Request validation failed"), request_id(request)
                ),
                status_code=422,
            )
        from fastapi.exception_handlers import request_validation_exception_handler

        return await request_validation_exception_handler(request, exc)

    def endpoint(operation):
        async def handle(request: Request, grant=Depends(auth)):
            if request.headers.get("FIP-Version", "v1") != "v1":
                raise ApiFault("unsupported_version", "Supported API version: v1", 426)
            if operation in WRITE_TYPES:
                if request.query_params:
                    raise ApiFault(
                        "invalid_request",
                        "Write operations accept only a JSON body and Idempotency-Key header",
                    )
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > 64000:
                        raise ApiFault(
                            "request_too_large", "FIP write body exceeds 64000 bytes", 413
                        )
                try:
                    value = json.loads(body)
                except (ValueError, UnicodeError):
                    raise ApiFault("invalid_json", "Body must be a JSON object") from None
                args = {
                    "record": value,
                    "idempotency_key": request.headers.get("Idempotency-Key", ""),
                }
            else:
                if len(request.query_params.multi_items()) != len(request.query_params):
                    raise ApiFault(
                        "invalid_request", "Duplicate query parameters are not supported"
                    )
                args = dict(request.query_params)
                args.update(request.path_params)
                args.setdefault("request_id", request_id(request))
                for name in ("limit", "max_response_bytes"):
                    if name in args:
                        try:
                            args[name] = int(args[name])
                        except ValueError:
                            raise ApiFault(
                                "invalid_request", "Pagination values must be integers"
                            ) from None
            return await asyncio.to_thread(service.execute, operation, args, grant)

        return handle

    for operation in OPERATIONS:
        method, path = ROUTES[operation]
        args_schema = BUNDLE["$defs"][operation + "Arguments"]
        parameters = []
        for name, schema in args_schema["properties"].items():
            if operation in WRITE_TYPES:
                break
            location = "path" if "{" + name in path else "query"
            parameters.append(
                {
                    "name": name,
                    "in": location,
                    "required": location == "path" or name in args_schema["required"],
                    "schema": schema,
                }
            )
        extra = {
            "parameters": parameters,
            "responses": {
                "200": {
                    "description": "FIP v1 response",
                    "content": {
                        "application/json": {
                            "schema": {"$ref": "#/components/schemas/" + operation + "Response"}
                        }
                    },
                }
            },
        }
        for code in (401, 403, 404, 409, 413, 422, 426, 500, 503):
            extra["responses"][str(code)] = {
                "description": "FIP ApiError",
                "content": {
                    "application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}
                },
            }
        if operation in WRITE_TYPES:
            extra["parameters"] = [
                {
                    "name": "Idempotency-Key",
                    "in": "header",
                    "required": True,
                    "schema": BUNDLE["$defs"][operation + "Arguments"]["properties"][
                        "idempotency_key"
                    ],
                }
            ]
            extra["requestBody"] = {
                "required": True,
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/" + WRITE_TYPES[operation]}
                    }
                },
            }
        app.add_api_route(
            path,
            endpoint(operation),
            methods=[method],
            operation_id="fip_v1_" + operation,
            tags=["FIP v1"],
            openapi_extra=extra,
        )

    # Primary evidence resolution is separate from the paginated history and never raw SQL.
    @app.get(
        "/v1/memory/projects/{project_id}/records/{record_id:path}",
        tags=["FIP v1 evidence"],
        responses={
            200: {
                "content": {
                    "application/json": {
                        "schema": {"$ref": "#/components/schemas/RecordLookupResponse"}
                    }
                }
            }
        },
    )
    def resolve(project_id: str, record_id: str, grant=Depends(auth)):
        if "read" not in grant.get("scopes", []):
            raise ApiFault("forbidden", "Read scope required", 403)
        service._scope(project_id, grant)
        records, _, _ = service._snapshot({"project_id": project_id}, grant)
        for kind, record in records:
            if record["record_id"] == record_id:
                result = {
                    **envelope(project_id=project_id),
                    "data": {"record_type": kind, "record": record},
                }
                validate("RecordLookupResponse", result)
                return result
        raise ApiFault("not_found", "Record not found", 404)

    original_openapi = app.openapi

    def openapi():
        schema = original_openapi()

        def rewrite(value):
            if isinstance(value, dict):
                return {
                    k: v.replace("urn:fip:v1#/$defs/", "#/components/schemas/")
                    if k == "$ref"
                    else rewrite(v)
                    for k, v in value.items()
                }
            if isinstance(value, list):
                return [rewrite(v) for v in value]
            return value

        schema.setdefault("components", {}).setdefault("schemas", {}).update(
            rewrite(BUNDLE["$defs"])
        )
        return schema

    app.openapi = openapi
    return service
