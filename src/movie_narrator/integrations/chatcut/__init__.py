"""Official ChatCut MCP integration boundary.

This package contains no database client and no guessed HTTP calls.  The
Codex host supplies the authenticated tool gateway; tests and other hosts can
inject a compatible callable.
"""

from .client import ChatCutClient, ChatCutConnectionReport, probe_chatcut_connection
from .timeline import CHATCUT_TRACKS, ChatCutTimelinePlan, build_timeline_plan

__all__ = [
    "CHATCUT_TRACKS",
    "ChatCutClient",
    "ChatCutConnectionReport",
    "ChatCutTimelinePlan",
    "build_timeline_plan",
    "probe_chatcut_connection",
]
