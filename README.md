# calibre-mcp-server

A remote MCP server that exposes a Calibre ebook library to Claude Code. Runs as a Docker container alongside Calibre and connects via HTTP/SSE.

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
| `CALIBRE_URL` | `http://localhost:8181` | Base URL of your Calibre content server. Used to generate EPUB download links in search results. |

## Running with Docker Compose

Add this service to your existing `docker-compose.yml`:

```yaml
  calibre-mcp:
    build: ./calibre-mcp
    container_name: calibre-mcp
    restart: unless-stopped
    ports:
      - 3000:3000
    environment:
      - CALIBRE_LIBRARY=/library
      - CALIBRE_URL=http://your-calibre-host:8181
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
  -e CALIBRE_URL=http://your-calibre-host:8181 \
  calibre-mcp-server
```

## Connecting to Claude Code

Once the container is running, register it as a remote MCP server:

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
| `search` | Search by title, author, series, tags. Supports Calibre field syntax (`title:"..."`, `authors:"..."`, etc.) or plain keywords. |
| `fts` | Full-text search across all book content. Requires the FTS index to be built in Calibre (Preferences → Search → Full text search). |
| `book` | Full metadata for a specific book by ID. |
| `read` | Extract chapter text from a book. Omit chapter number to list available chapters. |
| `search_book` | Search for specific passages within a single book. Useful for finding what a character did or said without reading the whole book. |
