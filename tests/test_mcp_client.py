"""MCP 协议层测试：用一个假 MCP Server 验证握手、SSE 解析与载荷抽取。"""

from __future__ import annotations

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_points_pal.mcp_client import (  # noqa: E402
    McpClient,
    McpError,
    extract_payload,
    parse_sse,
)


# ---------- 载荷抽取 ----------

def test_extract_payload_reads_json_directly():
    assert extract_payload('{"a": 1}') == {"a": 1}


def test_extract_payload_strips_human_readable_wrapper():
    """麦当劳 MCP 会在 JSON 前附一段说明，用 `## Original Response` 分隔。"""
    text = (
        "# API Response Information\n\n"
        "Below is the response from an API call.\n\n"
        "## Original Response\n\n"
        '{"success": true, "code": 200, "data": {"availablePoint": "536.8"}}'
    )
    payload = extract_payload(text)
    assert payload["data"]["availablePoint"] == "536.8"


def test_extract_payload_raises_on_garbage():
    with pytest.raises(McpError):
        extract_payload("不是 JSON 的内容")


# ---------- SSE ----------

def test_parse_sse_pulls_data_lines_only():
    body = (
        ": keep-alive\n"
        'event: message\n'
        'data: {"jsonrpc":"2.0","id":1,"result":{"ok":true}}\n'
        "\n"
        "data: [DONE]\n"
    )
    messages = parse_sse(body)
    assert len(messages) == 1
    assert messages[0]["id"] == 1


def test_parse_sse_tolerates_broken_chunk():
    assert parse_sse("data: not-json\ndata: {\"id\":2}\n") == [{"id": 2}]


# ---------- 假 MCP Server ----------

class FakeMcpHandler(BaseHTTPRequestHandler):
    server_version = "FakeMCP/1.0"

    def log_message(self, *_args):
        pass

    def _reply(self, payload, status=200, content_type="application/json",
               session=None):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        if session:
            self.send_header("Mcp-Session-Id", session)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        length = int(self.headers.get("Content-Length", 0))
        request = json.loads(self.rfile.read(length) or b"{}")
        auth = self.headers.get("Authorization", "")

        if auth != "Bearer test-token":
            self._reply({"error": "unauthorized"}, status=401)
            return

        method = request.get("method")
        request_id = request.get("id")

        if method == "initialize":
            self._reply(
                {"jsonrpc": "2.0", "id": request_id,
                 "result": {"protocolVersion": "2025-06-18",
                            "serverInfo": {"name": "fake", "version": "1"}}},
                session="fake-session-123",
            )
        elif method == "tools/list":
            self._reply(
                {"jsonrpc": "2.0", "id": request_id,
                 "result": {"tools": [{"name": "query-my-account", "description": "积分账户"}]}},
            )
        elif method == "tools/call":
            if self.headers.get("Mcp-Session-Id") != "fake-session-123":
                self._reply({"jsonrpc": "2.0", "id": request_id,
                             "error": {"code": -32001, "message": "no session"}}, status=400)
                return
            tool = request["params"]["name"]
            wrapped = ("# API Response Information\n\n## Original Response\n\n"
                       + json.dumps({"success": True, "data": {"tool": tool}}))
            sse = ("event: message\n"
                   'data: %s\n\n' % json.dumps(
                       {"jsonrpc": "2.0", "id": request_id,
                        "result": {"content": [{"type": "text", "text": wrapped}],
                                   "isError": False}}))
            body = sse.encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        else:
            self._reply({"jsonrpc": "2.0", "id": request_id,
                         "error": {"code": -32601, "message": "method not found"}}, status=400)


@pytest.fixture(scope="module")
def server():
    httpd = ThreadingHTTPServer(("127.0.0.1", 0), FakeMcpHandler)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    yield "http://127.0.0.1:%d" % httpd.server_address[1]
    httpd.shutdown()


def test_full_handshake_and_tool_call(server):
    with McpClient(token="test-token", url=server) as client:
        assert client.session_id == "fake-session-123"
        tools = client.list_tools()
        assert [t["name"] for t in tools] == ["query-my-account"]
        payload = client.call_tool("query-my-account")
        assert payload["data"]["tool"] == "query-my-account"


def test_missing_token_raises_immediately():
    with pytest.raises(McpError):
        McpClient(token="")


def test_wrong_token_is_reported(server):
    with pytest.raises(McpError):
        McpClient(token="bad", url=server).initialize()
