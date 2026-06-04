import unittest
import warnings

warnings.filterwarnings(
    "ignore",
    message="Using `httpx` with `starlette.testclient` is deprecated.*",
    category=Warning,
)

from starlette.routing import Mount, Route
from starlette.testclient import TestClient

import server


def route_paths(app):
    return {route.path: route for route in app.routes}


class TransportRouteTests(unittest.TestCase):
    def test_sse_routes_remain_available(self):
        routes = route_paths(server.app)

        self.assertIsInstance(routes["/sse"], Route)
        self.assertIsInstance(routes["/messages"], Mount)

    def test_streamable_http_route_is_mounted_at_mcp(self):
        routes = route_paths(server.app)

        self.assertIsInstance(routes["/mcp"], Mount)

    def test_streamable_http_initialize_post_returns_success(self):
        with TestClient(server.app) as client:
            response = client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 1,
                    "method": "initialize",
                    "params": {
                        "protocolVersion": "2025-03-26",
                        "capabilities": {},
                        "clientInfo": {"name": "test-client", "version": "0.0.0"},
                    },
                },
                headers={"Accept": "application/json, text/event-stream"},
            )

        self.assertEqual(response.status_code, 200)
        body = response.json()
        self.assertEqual(body["jsonrpc"], "2.0")
        self.assertEqual(body["id"], 1)
        self.assertIn("protocolVersion", body["result"])


if __name__ == "__main__":
    unittest.main()
