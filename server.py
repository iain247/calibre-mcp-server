#!/usr/bin/env python3

import asyncio
import json
import os
import re
import subprocess
from typing import Any

import uvicorn
from mcp import types
from mcp.server import Server
from mcp.server.sse import SseServerTransport
from starlette.applications import Starlette
from starlette.routing import Mount, Route

CALIBRE_LIBRARY = os.environ.get("CALIBRE_LIBRARY", "/library")
CALIBRE_URL = os.environ.get("CALIBRE_URL", "http://localhost:8181").rstrip("/")
TIMEOUT = 30

server = Server("calibre-mcp")


def _run_calibredb(*args: str) -> str:
    result = subprocess.run(
        ["calibredb", "--library-path", CALIBRE_LIBRARY, *args],
        capture_output=True,
        text=True,
        timeout=TIMEOUT,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"calibredb exited with code {result.returncode}")
    return result.stdout


async def run_calibredb(*args: str) -> str:
    return await asyncio.to_thread(_run_calibredb, *args)


def format_authors(authors: list[str] | str | None) -> str:
    if isinstance(authors, list):
        return ", ".join(authors)
    return authors or "Unknown"


def format_formats(formats: list[str] | None) -> list[str]:
    if not formats:
        return []
    return [os.path.splitext(f)[1].lstrip(".").upper() for f in formats]


def book_to_text(book: dict) -> str:
    lines = [
        f"ID: {book['id']}",
        f"Title: {book.get('title', 'Unknown')}",
        f"Authors: {format_authors(book.get('authors'))}",
    ]
    if book.get("series"):
        idx = book.get("series_index", "")
        lines.append(f"Series: {book['series']}" + (f" #{idx}" if idx else ""))
    if book.get("tags"):
        tags = book["tags"]
        lines.append(f"Tags: {', '.join(tags) if isinstance(tags, list) else tags}")
    if book.get("publisher"):
        lines.append(f"Publisher: {book['publisher']}")
    if book.get("pubdate"):
        lines.append(f"Published: {str(book['pubdate'])[:10]}")
    if book.get("rating"):
        lines.append(f"Rating: {book['rating']}/10")
    fmts = format_formats(book.get("formats"))
    if fmts:
        lines.append(f"Formats: {', '.join(fmts)}")
        if "EPUB" in fmts:
            lines.append(f"Download EPUB: {CALIBRE_URL}/get/EPUB/{book['id']}")
    if book.get("comments"):
        desc = re.sub(r"<[^>]+>", "", book["comments"]).strip()
        if desc:
            lines.append(f"\nDescription:\n{desc[:500]}")
    return "\n".join(lines)


@server.list_tools()
async def list_tools() -> list[types.Tool]:
    return [
        types.Tool(
            name="search",
            description=(
                "Search the Calibre library by metadata. "
                "Supports Calibre field syntax: title:\"...\", authors:\"...\", "
                "series:\"...\", tags:\"...\", or plain keywords."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Search query (Calibre field syntax or plain keywords)",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Max results to return (default: 25)",
                        "default": 25,
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="fts",
            description=(
                "Full-text search inside book content. "
                "Requires the FTS index to be built in Calibre "
                "(Preferences → Search → Full text search). "
                "Returns books containing the search terms with matching snippets."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "Text to search for inside books",
                    },
                },
                "required": ["query"],
            },
        ),
        types.Tool(
            name="book",
            description="Get full metadata for a specific book by its Calibre ID.",
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Calibre book ID",
                    },
                },
                "required": ["id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "search":
            return await handle_search(arguments)
        elif name == "fts":
            return await handle_fts(arguments)
        elif name == "book":
            return await handle_book(arguments)
        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except subprocess.TimeoutExpired:
        return [types.TextContent(type="text", text="Error: calibredb timed out after 30 seconds")]
    except RuntimeError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def handle_search(args: dict) -> list[types.TextContent]:
    query = args["query"]
    limit = int(args.get("limit", 25))

    output = await run_calibredb(
        "list",
        "--fields", "id,title,authors,series,series_index,tags,formats",
        "--for-machine",
        "--limit", str(limit),
        "--search", query,
    )

    books = json.loads(output or "[]")
    if not books:
        return [types.TextContent(type="text", text=f"No books found for: {query}")]

    lines = [f"Found {len(books)} book(s) for '{query}':\n"]
    for book in books:
        lines.append(book_to_text(book))
        lines.append("")
    return [types.TextContent(type="text", text="\n".join(lines).strip())]


async def handle_fts(args: dict) -> list[types.TextContent]:
    query = args["query"]

    output = await run_calibredb(
        "fts_search",
        "--output-format", "json",
        query,
    )

    results = json.loads(output or "[]")
    if not results:
        return [types.TextContent(
            type="text",
            text=(
                f"No full-text results for: {query}\n"
                "Note: the FTS index must be built in Calibre "
                "(Preferences → Search → Full text search)."
            ),
        )]

    lines = [f"Found {len(results)} full-text match(es) for '{query}':\n"]
    for r in results:
        lines.append(f"Book ID {r.get('book_id')}: {r.get('title', 'Unknown')}")
        if r.get("text"):
            lines.append(f"  Snippet: ...{r['text'].strip()}...")
        lines.append("")
    return [types.TextContent(type="text", text="\n".join(lines).strip())]


async def handle_book(args: dict) -> list[types.TextContent]:
    book_id = int(args["id"])

    output = await run_calibredb(
        "list",
        "--fields", "id,title,authors,series,series_index,tags,publisher,pubdate,comments,formats,identifiers,rating",
        "--for-machine",
        "--search", f"id:{book_id}",
    )

    books = json.loads(output or "[]")
    if not books:
        return [types.TextContent(type="text", text=f"No book found with ID: {book_id}")]

    return [types.TextContent(type="text", text=book_to_text(books[0]))]


sse = SseServerTransport("/messages")


async def handle_sse(request):
    async with sse.connect_sse(request.scope, request.receive, request._send) as streams:
        await server.run(streams[0], streams[1], server.create_initialization_options())


app = Starlette(
    routes=[
        Route("/sse", endpoint=handle_sse),
        Mount("/messages", app=sse.handle_post_message),
    ]
)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=3000, log_level="info")
