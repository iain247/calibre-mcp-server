# Agent Guide

## What this is

A Python MCP server that bridges MCP clients to a Calibre ebook library. It exposes legacy SSE at `/sse` for Claude Code and streamable HTTP at `/mcp` for Codex/newer MCP clients, then shells out to `calibredb` for library queries and EPUB access.

## Key files

- `server.py` — everything: MCP server setup, tool definitions, calibredb calls, EPUB parsing
- `Dockerfile` — python:3.12-slim + calibre via apt
- `requirements.txt` — mcp, uvicorn, starlette

## How to run locally for testing

```bash
pip install -r requirements.txt
CALIBRE_LIBRARY=/path/to/library python server.py
```

The server starts on `http://0.0.0.0:3000`. Tools are available through SSE at `/sse` and streamable HTTP at `/mcp`.

## Adding a tool

1. Add a `types.Tool(...)` entry in `list_tools()`
2. Add a `handle_*` async function
3. Add an `elif name == "..."` case in `call_tool()`

Tool handlers receive `args: dict` and return `list[types.TextContent]`. All blocking work (calibredb calls, file I/O) must go through `asyncio.to_thread`.

## calibredb

All library queries use `calibredb --library-path $CALIBRE_LIBRARY`. The `run_calibredb(*args)` helper handles the subprocess call, timeout, and error raising. Use `--for-machine` with `calibredb list` to get JSON output.

## EPUB parsing

EPUBs are zip files. `get_epub_chapters(path)` returns a list of `{title, file}` from the NCX table of contents (falls back to OPF spine). `extract_chapter_text(path, file)` returns clean text stripped of HTML tags. Both use Python stdlib only.
