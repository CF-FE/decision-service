import logging
import sqlite3
from typing import Self

from mcp.server import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import INVALID_PARAMS, CallToolResult, ListToolsResult, TextContent, Tool, ToolAnnotations
from pydantic import ValidationError, model_validator
from starlette.concurrency import run_in_threadpool
from starlette.datastructures import Headers
from starlette.responses import JSONResponse

from .errors import APIError, ERRORS, error_payload
from .models import Evaluate, Feedback, StrictModel
from .settings import Name
from .storage import canonical

logger = logging.getLogger(__name__)


class DecisionLookup(StrictModel):
    decision_id: Name | None = None
    request_id: Name | None = None

    @model_validator(mode="after")
    def one_identifier(self) -> Self:
        if len(self.model_fields_set) != 1 or (self.decision_id is None and self.request_id is None):
            raise ValueError("provide exactly one decision_id or request_id")
        return self


class DecisionMCPEndpoint:
    def __init__(self, settings, caller_for_bearer, evaluate, read_decision, record_feedback, oauth):
        self.caller_for_bearer = caller_for_bearer
        self.oauth = oauth
        lookup_schema = DecisionLookup.model_json_schema()
        lookup_schema["oneOf"] = [{"required": ["decision_id"]}, {"required": ["request_id"]}]
        tools = [
            Tool(
                name="evaluate_decision",
                description="Evaluate a finite question with the Decision Service v1 request fields.",
                inputSchema=Evaluate.model_json_schema(),
                annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=False, openWorldHint=True),
            ),
            Tool(
                name="get_decision",
                description="Read a stored decision and its feedback by decision_id or request_id.",
                inputSchema=lookup_schema,
                annotations=ToolAnnotations(readOnlyHint=True, openWorldHint=False),
            ),
            Tool(
                name="record_decision_feedback",
                description="Record a v1 application, result or correction for a stored decision.",
                inputSchema=Feedback.model_json_schema(),
                annotations=ToolAnnotations(
                    readOnlyHint=False, destructiveHint=False, idempotentHint=True, openWorldHint=False
                ),
            ),
        ]

        async def list_tools(ctx, params):
            return ListToolsResult(tools=tools)

        async def call_tool(ctx, params):
            args = params.arguments or {}
            try:
                caller = None if ctx.request is None else getattr(ctx.request.state, "decision_caller", None)
                if caller is None:
                    raise APIError("unauthenticated")
                if params.name == "evaluate_decision":
                    result = await run_in_threadpool(evaluate, Evaluate.model_validate(args), caller)
                elif params.name == "get_decision":
                    lookup = DecisionLookup.model_validate(args)
                    result = await run_in_threadpool(read_decision, caller, lookup.decision_id, lookup.request_id)
                elif params.name == "record_decision_feedback":
                    result = await run_in_threadpool(record_feedback, Feedback.model_validate(args), caller)
                else:
                    raise MCPError(INVALID_PARAMS, "Unknown Decision Service tool.")
            except ValidationError:
                result = error_payload("invalid_request")
            except APIError as exc:
                result = error_payload(exc.code, **exc.refs)
            except sqlite3.Error as exc:
                logger.error("SQLite operation failed (%s)", type(exc).__name__)
                result = error_payload("unavailable")
            return CallToolResult(
                content=[TextContent(type="text", text=canonical(result))],
                structuredContent=result,
                isError="error" in result,
            )

        server = Server("decision-service", version="1.0", on_list_tools=list_tools, on_call_tool=call_tool)
        self.manager = StreamableHTTPSessionManager(
            server, stateless=True, json_response=True,
            security_settings=TransportSecuritySettings(
                allowed_hosts=[
                    "127.0.0.1", "127.0.0.1:*", "localhost", "localhost:*", "[::1]", "[::1]:*",
                    *settings.mcp_allowed_hosts,
                ],
                allowed_origins=settings.mcp_allowed_origins,
            ),
        )

    async def __call__(self, scope, receive, send):
        authorization = Headers(scope=scope).get("authorization")
        try:
            caller = self.caller_for_bearer(authorization)
            if caller is None:
                if self.oauth is None:
                    raise APIError("unauthenticated")
                caller = await self.oauth.authenticate(authorization)
        except APIError as exc:
            status, _ = ERRORS[exc.code]
            challenge = self.oauth.challenge if self.oauth is not None else "Bearer"
            headers = {"WWW-Authenticate": challenge} if status == 401 else None
            response = JSONResponse(error_payload(exc.code), status, headers=headers)
            await response(scope, receive, send)
            return
        scope = {**scope, "state": {**scope.get("state", {}), "decision_caller": caller}}
        await self.manager.handle_request(scope, receive, send)
