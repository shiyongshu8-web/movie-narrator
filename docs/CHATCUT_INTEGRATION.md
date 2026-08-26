# ChatCut integration

`movie-narrator` keeps its existing FFmpeg renderer and adds an editable
backend boundary for the official ChatCut Agent Plugin only:

- repository: `https://github.com/ChatCut-Inc/agent-plugin`
- MCP endpoint: `https://api.chatcut.io/api/external-mcp/mcp`
- Codex server name: `chatcut`
- authentication: `codex mcp login chatcut`

The Python package does not make guessed HTTP calls and does not access a
ChatCut database. The authenticated Codex host supplies the MCP tool gateway;
`movie_narrator.integrations.chatcut.ChatCutClient` accepts that gateway by
injection. This keeps project IDs, timeline IDs, item IDs, and asset IDs
source-of-truth values returned by ChatCut rather than inferred locally.

## Connection gate

Run:

```powershell
codex mcp get chatcut
codex mcp login chatcut       # only when the server asks for authentication
movie-narrator chatcut status
```

`chatcut status` reports `PASS`, `FAIL`, or `UNKNOWN` for:
`mcp_configured`, `authenticated`, `project_access`, `timeline_access`,
`asset_access`, `edit_access`, `preview_access`, and `export_access`.
The current code deliberately does not treat an installed plugin, a local
timeline plan, or a successful shell command as proof that a live ChatCut
edit happened.

## Readback rule

The live adapter must:

1. read/target the exact project and timeline;
2. read the current timeline before mutation;
3. apply one auditable edit through the official MCP tools;
4. read the timeline again and inspect affected items;
5. refresh `SYNC_MAP.json` and rerun semantic alignment QC;
6. inspect a composed timeline preview before reporting visible success.

Any trim, split, move, replace, speed, or ripple operation invalidates the
previous timeline coordinates. Its old sync rows are `STALE` until readback.

## Track contract

The logical ChatCut plan uses fixed roles:

| Track | Role |
| --- | --- |
| V1 | original picture |
| V2 | B-roll / emphasis |
| V3 | graphics |
| A1 | original dialogue and sound |
| A2 | narration |
| A3 | BGM |
| A4 | SFX |
| C1 | captions |

This is a logical plan, not permission to invent hidden ChatCut track IDs.
Real IDs must come from project/timeline readback.

## Current environment note

If `mcp__chatcut__*` tools are not visible, do not reinstall a similarly
named project or call a private endpoint. Authenticate `chatcut` in Codex;
if the tools still do not appear, start a new Codex session and recheck.
