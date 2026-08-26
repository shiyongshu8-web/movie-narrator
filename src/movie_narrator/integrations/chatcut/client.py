# SPDX-License-Identifier: AGPL-3.0-or-later

"""Transport-neutral client for the official ChatCut MCP tool surface."""

from __future__ import annotations

import shutil
import subprocess
from dataclasses import dataclass
from typing import Any, Callable, Mapping, Protocol

from pydantic import BaseModel


CHATCUT_MCP_ENDPOINT = "https://api.chatcut.io/api/external-mcp/mcp"
CHATCUT_EDIT_ITEM_KEYS = frozenset(
    {"adds", "updates", "deletes", "json", "ripple", "validateOnly", "projectId"}
)


class ChatCutConnectionReport(BaseModel):
    """Connection report; ``None`` means evidence was not available."""

    mcp_configured: bool | None = None
    authenticated: bool | None = None
    project_access: bool | None = None
    timeline_access: bool | None = None
    asset_access: bool | None = None
    edit_access: bool | None = None
    preview_access: bool | None = None
    export_access: bool | None = None
    endpoint: str = CHATCUT_MCP_ENDPOINT
    detail: str = ""

    @property
    def ready_for_edit(self) -> bool:
        required = (
            self.mcp_configured,
            self.authenticated,
            self.project_access,
            self.timeline_access,
            self.edit_access,
        )
        return all(value is True for value in required)

    def as_text(self) -> str:
        def state(value: bool | None) -> str:
            return "PASS" if value is True else "FAIL" if value is False else "UNKNOWN"

        lines = ["CHATCUT_CONNECTION_REPORT"]
        for field in (
            "mcp_configured",
            "authenticated",
            "project_access",
            "timeline_access",
            "asset_access",
            "edit_access",
            "preview_access",
            "export_access",
        ):
            lines.append(f"{field} = {state(getattr(self, field))}")
        lines.append(f"endpoint = {self.endpoint}")
        if self.detail:
            lines.append(f"detail = {self.detail}")
        return "\n".join(lines)


class ChatCutToolGateway(Protocol):
    def __call__(self, tool_name: str, arguments: Mapping[str, Any]) -> Any: ...


@dataclass
class ChatCutClient:
    """Call official MCP tools through an injected host gateway.

    The gateway is deliberately injected because the Codex MCP connector is a
    host capability, not a Python HTTP API.  This also makes all mutations
    auditable and straightforward to fake in tests.
    """

    gateway: ChatCutToolGateway

    def call(self, tool_name: str, **arguments: Any) -> Any:
        return self.gateway(tool_name, arguments)

    def read_project(self, project_id: str | None = None) -> Any:
        args = {"projectId": project_id} if project_id else {}
        return self.call("read_project", **args)

    def read_timeline(
        self,
        *,
        project_id: str | None = None,
        timeline_id: str | None = None,
        views: list[str] | None = None,
    ) -> Any:
        args: dict[str, Any] = {}
        if project_id:
            args["projectId"] = project_id
        if timeline_id:
            args["timelineId"] = timeline_id
        if views:
            args["views"] = views
        return self.call("preview_timeline", **args)

    def browse_assets(self, *, project_id: str | None = None) -> Any:
        return self.call("browse_assets", **({"projectId": project_id} if project_id else {}))

    def inspect_item(self, item_id: str, *, project_id: str | None = None) -> Any:
        args: dict[str, Any] = {"itemId": item_id}
        if project_id:
            args["projectId"] = project_id
        return self.call("inspect_item", **args)

    def apply_edit(self, edit: Mapping[str, Any], *, project_id: str | None = None) -> Any:
        """Submit a canonical ``edit_item`` payload through the host gateway.

        The official MCP tool accepts ``adds``/``updates``/``deletes`` (or its
        legacy ``json`` wrapper), not a free-form ``operation`` object.  A
        semantic ``RepairOperation`` must be resolved to concrete item IDs and
        frame edits by the host adapter before it reaches this method.
        """

        args = dict(edit)
        nested = args.pop("operation", None)
        if nested is not None:
            if args or not isinstance(nested, Mapping):
                raise ValueError("operation must be replaced by a canonical edit_item payload")
            args = dict(nested)
        unknown = set(args).difference(CHATCUT_EDIT_ITEM_KEYS)
        if unknown:
            names = ", ".join(sorted(unknown))
            raise ValueError(
                "semantic repair operations require a host-side item/frame mapping; "
                f"unsupported edit_item fields: {names}"
            )
        if project_id:
            args["projectId"] = project_id
        return self.call("edit_item", **args)

    def render_preview(self, *, project_id: str | None = None, timeline_id: str | None = None) -> Any:
        args: dict[str, Any] = {"views": ["viewer"]}
        if project_id:
            args["projectId"] = project_id
        if timeline_id:
            args["timelineId"] = timeline_id
        return self.call("preview_timeline", **args)

    def submit_export(self, *, project_id: str | None = None, timeline_id: str | None = None) -> Any:
        args: dict[str, Any] = {}
        if project_id:
            args["projectId"] = project_id
        if timeline_id:
            args["timelineId"] = timeline_id
        return self.call("submit_export", **args)


def _parse_connection_output(output: str, *, returncode: int) -> ChatCutConnectionReport:
    lower = output.lower()
    configured = CHATCUT_MCP_ENDPOINT.lower() in lower or (
        "chatcut" in lower and ("mcp" in lower or "server" in lower)
    )
    if "needs authentication" in lower or "unauthorized" in lower or "401" in lower:
        authenticated: bool | None = False
    elif "connected" in lower or "authenticated" in lower:
        authenticated = returncode == 0
    else:
        authenticated = None
    return ChatCutConnectionReport(
        mcp_configured=configured if output else None,
        authenticated=authenticated,
        detail=(
            "codex CLI returned a non-zero status"
            if returncode != 0
            else "server status parsed from codex mcp get"
        ),
    )


def probe_chatcut_connection(
    *,
    command_runner: Callable[..., Any] | None = None,
) -> ChatCutConnectionReport:
    """Run the read-only ``codex mcp get chatcut`` probe when possible."""

    executable = shutil.which("codex")
    if not executable:
        return ChatCutConnectionReport(detail="codex CLI is not on PATH")
    runner = command_runner or subprocess.run
    try:
        result = runner(
            [executable, "mcp", "get", "chatcut"],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ChatCutConnectionReport(detail=f"codex CLI probe failed: {type(exc).__name__}")
    output = f"{result.stdout or ''}\n{result.stderr or ''}"
    report = _parse_connection_output(output, returncode=int(result.returncode))
    if report.mcp_configured is False:
        report.detail = "chatcut MCP server is not configured"
    return report
