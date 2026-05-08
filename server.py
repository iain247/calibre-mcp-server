#!/usr/bin/env python3

import asyncio
import json
import os
import re
import subprocess
import xml.etree.ElementTree as ET
import zipfile
from html.parser import HTMLParser
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


class _HTMLTextExtractor(HTMLParser):
    def __init__(self):
        super().__init__()
        self._text = []
        self._skip = False

    def handle_starttag(self, tag, attrs):
        if tag in ('script', 'style'):
            self._skip = True
        elif tag in ('p', 'div', 'h1', 'h2', 'h3', 'h4', 'h5', 'h6', 'br', 'tr'):
            self._text.append('\n')

    def handle_endtag(self, tag):
        if tag in ('script', 'style'):
            self._skip = False

    def handle_data(self, data):
        if not self._skip:
            self._text.append(data)

    def get_text(self):
        return ''.join(self._text)


def _parse_ncx(z: zipfile.ZipFile, ncx_name: str) -> list[dict]:
    ns = {'ncx': 'http://www.daisy.org/z3986/2005/ncx/'}
    root = ET.fromstring(z.read(ncx_name))
    base = ncx_name.rsplit('/', 1)[0] + '/' if '/' in ncx_name else ''
    names = z.namelist()
    chapters = []
    for point in root.findall('.//ncx:navPoint', ns):
        label = point.find('.//ncx:text', ns)
        content = point.find('ncx:content', ns)
        if label is None or content is None:
            continue
        src = content.get('src', '').split('#')[0]
        path = (base + src) if not src.startswith('/') else src.lstrip('/')
        file_path = path if path in names else src
        if file_path in names:
            chapters.append({'title': label.text or f"Chapter {len(chapters) + 1}", 'file': file_path})
    return chapters


def _parse_spine(z: zipfile.ZipFile) -> list[dict]:
    names = z.namelist()
    opf_name = next((n for n in names if n.endswith('.opf')), None)
    if not opf_name:
        return []
    ns = {'opf': 'http://www.idpf.org/2007/opf'}
    root = ET.fromstring(z.read(opf_name))
    base = opf_name.rsplit('/', 1)[0] + '/' if '/' in opf_name else ''
    manifest = {item.get('id'): base + item.get('href', '') for item in root.findall('.//opf:item', ns)}
    chapters = []
    for itemref in root.findall('.//opf:itemref', ns):
        path = manifest.get(itemref.get('idref', ''))
        if path and path in names:
            chapters.append({'title': f"Section {len(chapters) + 1}", 'file': path})
    return chapters


def get_epub_chapters(epub_path: str) -> list[dict]:
    with zipfile.ZipFile(epub_path) as z:
        ncx = next((n for n in z.namelist() if n.endswith('.ncx')), None)
        return _parse_ncx(z, ncx) if ncx else _parse_spine(z)


def extract_chapter_text(epub_path: str, chapter_file: str) -> str:
    with zipfile.ZipFile(epub_path) as z:
        html = z.read(chapter_file).decode('utf-8', errors='replace')
    extractor = _HTMLTextExtractor()
    extractor.feed(html)
    text = extractor.get_text()
    return re.sub(r'\n{3,}', '\n\n', text).strip()


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
            name="list_all",
            description="List every book in the Calibre library with title, authors, series and formats. Use this when the user wants to see their full library.",
            inputSchema={
                "type": "object",
                "properties": {},
            },
        ),
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
        types.Tool(
            name="search_book",
            description=(
                "Search for specific passages within a single book. "
                "Useful for finding what a character said or did, locating a scene, "
                "or answering questions about specific events without reading the whole book."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Calibre book ID",
                    },
                    "query": {
                        "type": "string",
                        "description": "Word or phrase to search for",
                    },
                    "max_results": {
                        "type": "integer",
                        "description": "Maximum number of matching passages to return (default: 10)",
                        "default": 10,
                    },
                },
                "required": ["id", "query"],
            },
        ),
        types.Tool(
            name="read",
            description=(
                "Read the text of a specific chapter from a book in your Calibre library. "
                "If no chapter number is given, returns the list of available chapters. "
                "Use the book ID from search results."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "id": {
                        "type": "integer",
                        "description": "Calibre book ID",
                    },
                    "chapter": {
                        "type": "integer",
                        "description": "Chapter number (1-indexed). Omit to list available chapters.",
                    },
                },
                "required": ["id"],
            },
        ),
    ]


@server.call_tool()
async def call_tool(name: str, arguments: dict[str, Any]) -> list[types.TextContent]:
    try:
        if name == "list_all":
            return await handle_list_all()
        elif name == "search":
            return await handle_search(arguments)
        elif name == "fts":
            return await handle_fts(arguments)
        elif name == "book":
            return await handle_book(arguments)
        elif name == "read":
            return await handle_read(arguments)
        elif name == "search_book":
            return await handle_search_book(arguments)
        else:
            return [types.TextContent(type="text", text=f"Unknown tool: {name}")]
    except subprocess.TimeoutExpired:
        return [types.TextContent(type="text", text="Error: calibredb timed out after 30 seconds")]
    except RuntimeError as e:
        return [types.TextContent(type="text", text=f"Error: {e}")]


async def handle_list_all() -> list[types.TextContent]:
    output = await run_calibredb(
        "list",
        "--fields", "id,title,authors,series,series_index,formats",
        "--for-machine",
    )
    books = json.loads(output or "[]")
    if not books:
        return [types.TextContent(type="text", text="No books found in library.")]

    lines = [f"{len(books)} book(s) in library:\n"]
    for book in books:
        lines.append(book_to_text(book))
        lines.append("")
    return [types.TextContent(type="text", text="\n".join(lines).strip())]


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


async def handle_search_book(args: dict) -> list[types.TextContent]:
    book_id = int(args["id"])
    query = args["query"]
    max_results = int(args.get("max_results", 10))

    output = await run_calibredb(
        "list",
        "--fields", "id,title,formats",
        "--for-machine",
        "--search", f"id:{book_id}",
    )
    books = json.loads(output or "[]")
    if not books:
        return [types.TextContent(type="text", text=f"No book found with ID: {book_id}")]

    epub_path = next((f for f in books[0].get("formats", []) if f.lower().endswith(".epub")), None)
    if not epub_path:
        return [types.TextContent(type="text", text=f"No EPUB available for book {book_id}")]

    def search_epub():
        chapters = get_epub_chapters(epub_path)
        pattern = re.compile(re.escape(query), re.IGNORECASE)
        matches = []
        for i, ch in enumerate(chapters, 1):
            try:
                text = extract_chapter_text(epub_path, ch["file"])
            except Exception:
                continue
            for m in pattern.finditer(text):
                start = max(0, m.start() - 200)
                end = min(len(text), m.end() + 200)
                snippet = text[start:end].strip()
                matches.append((i, ch["title"], snippet))
                if len(matches) >= max_results:
                    return matches
        return matches

    try:
        matches = await asyncio.to_thread(search_epub)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error searching EPUB: {e}")]

    if not matches:
        return [types.TextContent(type="text", text=f"No matches for '{query}' in book {book_id}.")]

    title = books[0].get("title", f"Book {book_id}")
    lines = [f"{len(matches)} match(es) for '{query}' in {title}:\n"]
    for chapter_num, chapter_title, snippet in matches:
        lines.append(f"Chapter {chapter_num} — {chapter_title}:")
        lines.append(f"  ...{snippet}...")
        lines.append("")
    return [types.TextContent(type="text", text="\n".join(lines).strip())]


async def handle_read(args: dict) -> list[types.TextContent]:
    book_id = int(args["id"])
    chapter = args.get("chapter")

    output = await run_calibredb(
        "list",
        "--fields", "id,formats",
        "--for-machine",
        "--search", f"id:{book_id}",
    )
    books = json.loads(output or "[]")
    if not books:
        return [types.TextContent(type="text", text=f"No book found with ID: {book_id}")]

    formats = books[0].get("formats", [])
    epub_path = next((f for f in formats if f.lower().endswith(".epub")), None)
    if not epub_path:
        return [types.TextContent(type="text", text=f"No EPUB available for book {book_id}")]

    try:
        chapters = await asyncio.to_thread(get_epub_chapters, epub_path)
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error reading EPUB: {e}")]

    if chapter is None:
        lines = [f"{len(chapters)} chapter(s) available:\n"]
        for i, ch in enumerate(chapters, 1):
            lines.append(f"{i}. {ch['title']}")
        return [types.TextContent(type="text", text="\n".join(lines))]

    chapter_num = int(chapter)
    if chapter_num < 1 or chapter_num > len(chapters):
        return [types.TextContent(type="text", text=f"Chapter {chapter_num} not found — book has {len(chapters)} chapters.")]

    ch = chapters[chapter_num - 1]
    try:
        text = await asyncio.to_thread(extract_chapter_text, epub_path, ch["file"])
    except Exception as e:
        return [types.TextContent(type="text", text=f"Error extracting chapter: {e}")]

    return [types.TextContent(type="text", text=f"Chapter {chapter_num}: {ch['title']}\n\n{text}")]


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
