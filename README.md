# calibre-mcp-server

A remote MCP server that exposes a Calibre ebook library to MCP clients. Runs as a Docker container alongside Calibre and supports both legacy HTTP/SSE and streamable HTTP transports.

## Requirements

- Docker
- A Calibre library directory (the folder containing `metadata.db` and your book folders)

## Library path

Your Calibre library is a single directory that contains both `metadata.db` (the database) and your books organised into `Author/Title/` subfolders. You need to mount this directory into the container.

To find it: in the Calibre desktop app, hover over the library name in the top-right — it shows the full path. Or look for the folder containing `metadata.db`.

## Configuration

| Variable | Default | Description |
|----------|---------|-------------|
| `CALIBRE_LIBRARY` | `/library` | Where the library is mounted inside the container. Change this if you mount to a different path. |

## Running with Docker Compose

Add this service to your existing `docker-compose.yml`:

```yaml
  calibre-mcp:
    image: iain247/calibre-mcp-server:latest
    container_name: calibre-mcp
    restart: unless-stopped
    ports:
      - 3000:3000
    environment:
      - CALIBRE_LIBRARY=/library
    volumes:
      - /path/to/your/calibre/library:/library
```

The source files should be in a subdirectory named `calibre-mcp` relative to your `docker-compose.yml`.

## Running standalone

```bash
docker build -t calibre-mcp-server .
docker run -d \
  -p 3000:3000 \
  -v /path/to/your/calibre/library:/library \
  calibre-mcp-server
```

## Connecting to clients

The server exposes two MCP transports:

| Client type | URL | Notes |
|-------------|-----|-------|
| Streamable HTTP | `http://your-host:3000/mcp` | Recommended for Codex and newer MCP clients. |
| SSE | `http://your-host:3000/sse` | Kept for Claude Code configurations that use `--transport sse`. |

### Codex

Once the container is running, register it as a streamable HTTP MCP server:

```bash
codex mcp add calibre --url http://your-host:3000/mcp
```

Replace `your-host` with the IP or hostname of the machine running the container.

Verify it connected:

```bash
codex mcp list
```

### Claude Code

Claude Code can continue to use the SSE endpoint:

```bash
claude mcp add --transport sse --scope user calibre http://your-host:3000/sse
```

Use `--scope user` to make it available in all projects. Replace `your-host` with the IP or hostname of the machine running the container.

Verify it connected:

```bash
claude mcp list
```

You should see `calibre: http://your-host:3000/sse - ✓ Connected`.

## Tools

| Tool | Description |
|------|-------------|
| `list_all` | List every book in the library with title, authors, series and formats. |
| `search` | Search by title, author, series, tags. Supports Calibre field syntax (`title:"..."`, `authors:"..."`, etc.) or plain keywords. |
| `fts` | Full-text search across all book content. Requires the FTS index to be built in Calibre (Preferences → Search → Full text search). |
| `book` | Full metadata for a specific book by ID. |
| `read` | Extract chapter text from a book. Omit chapter number to list available chapters. |
| `search_book` | Search for specific passages within a single book. Useful for finding what a character did or said without reading the whole book. |
