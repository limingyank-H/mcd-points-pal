"""麦当劳 MCP 客户端（Streamable HTTP + JSON-RPC 2.0）。

零依赖，只用标准库。这是「真实使用麦当劳 MCP 能力」的那一层：
除了 `--mock` 离线模式，本项目的所有数据都从这里来。

用法：
    with McpClient(token=os.environ["MCD_MCP_TOKEN"]) as c:
        account = c.call_tool("query-my-account")
        coupons = c.call_tool("mall-points-products", {"catRuleIds": "1>4"})
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Dict, List, Optional

DEFAULT_URL = "https://mcp.mcd.cn"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "mcd-points-pal", "version": "1.0.0"}


class McpError(RuntimeError):
    """MCP 传输层或协议层错误。"""


class McpToolError(McpError):
    """工具本身返回了错误（isError=true）。"""


def extract_payload(text: str) -> Any:
    """从工具返回的文本里取出真正的 JSON 载荷。

    麦当劳 MCP 的文本内容会在 JSON 前面附一段人类可读的说明
    （以 `## Original Response` 分隔）。这里先把那段剥掉，
    再退回「从头找第一个 JSON 对象」的通用策略。
    """
    if not text:
        raise McpError("工具返回了空内容")

    marker = "## Original Response"
    if marker in text:
        text = text.split(marker, 1)[1].strip()

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char in "{[":
            try:
                obj, _ = decoder.raw_decode(text[index:])
                return obj
            except json.JSONDecodeError:
                continue
    raise McpError("无法从工具返回中解析出 JSON：%s" % text[:200])


def parse_sse(body: str) -> List[Dict[str, Any]]:
    """解析 text/event-stream 响应体，返回其中的 JSON-RPC 报文列表。"""
    messages: List[Dict[str, Any]] = []
    for line in body.splitlines():
        line = line.strip()
        if not line.startswith("data:"):
            continue
        chunk = line[len("data:"):].strip()
        if not chunk or chunk == "[DONE]":
            continue
        try:
            messages.append(json.loads(chunk))
        except json.JSONDecodeError:
            continue
    return messages


class McpClient:
    """极简 MCP Streamable HTTP 客户端。"""

    def __init__(self, token: str, url: str = DEFAULT_URL, timeout: int = 30):
        if not token:
            raise McpError("缺少 MCP Token：请设置环境变量 MCD_MCP_TOKEN")
        self.token = token
        self.url = url.rstrip("/")
        self.timeout = timeout
        self.session_id: Optional[str] = None
        self._next_id = 0
        self._tools: Optional[List[Dict[str, Any]]] = None

    # ---------- 传输 ----------

    def _headers(self, with_session: bool = True) -> Dict[str, str]:
        headers = {
            "Authorization": "Bearer %s" % self.token,
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
            "User-Agent": CLIENT_INFO["name"],
        }
        if with_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _post(self, payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        request = urllib.request.Request(
            self.url,
            data=json.dumps(payload).encode("utf-8"),
            headers=self._headers(),
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as response:
                session = response.headers.get("Mcp-Session-Id")
                if session:
                    self.session_id = session
                content_type = response.headers.get("Content-Type", "")
                body = response.read().decode("utf-8")
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:300]
            raise McpError("HTTP %s：%s" % (exc.code, detail)) from exc
        except urllib.error.URLError as exc:
            raise McpError("网络错误：%s" % exc.reason) from exc

        if not body.strip():
            return None

        if "text/event-stream" in content_type:
            messages = parse_sse(body)
            for message in messages:
                if message.get("id") == payload.get("id"):
                    return message
            if messages:
                return None
            # 有些实现声明了 SSE 却直接吐 JSON —— 兜底再试一次
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return None

        try:
            return json.loads(body)
        except json.JSONDecodeError as exc:
            raise McpError("响应不是合法 JSON：%s" % body[:200]) from exc

    # ---------- 协议 ----------

    def initialize(self) -> Dict[str, Any]:
        self._next_id += 1
        result = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "initialize",
                "params": {
                    "protocolVersion": PROTOCOL_VERSION,
                    "capabilities": {},
                    "clientInfo": CLIENT_INFO,
                },
            }
        )
        if not result or "result" not in result:
            raise McpError("initialize 失败：%s" % json.dumps(result, ensure_ascii=False)[:200])
        # 按协议要求回一条 initialized 通知（无 id，无响应）
        try:
            self._post({"jsonrpc": "2.0", "method": "notifications/initialized", "params": {}})
        except McpError:
            pass
        return result["result"]

    def list_tools(self) -> List[Dict[str, Any]]:
        if self._tools is not None:
            return self._tools
        self._next_id += 1
        result = self._post(
            {"jsonrpc": "2.0", "id": self._next_id, "method": "tools/list", "params": {}}
        )
        if not result or "result" not in result:
            raise McpError("tools/list 失败")
        self._tools = result["result"].get("tools", [])
        return self._tools

    def call_tool(self, name: str, arguments: Optional[Dict[str, Any]] = None) -> Any:
        """调用工具并返回解析后的 JSON 载荷。"""
        self._next_id += 1
        message = self._post(
            {
                "jsonrpc": "2.0",
                "id": self._next_id,
                "method": "tools/call",
                "params": {"name": name, "arguments": arguments or {}},
            }
        )
        if not message:
            raise McpError("工具 %s 没有返回内容" % name)
        if "error" in message:
            raise McpError("工具 %s 报错：%s" % (name, message["error"]))

        result = message.get("result") or {}
        texts = [c.get("text", "") for c in result.get("content", []) if c.get("type") == "text"]
        if result.get("isError"):
            raise McpToolError("工具 %s 返回错误：%s" % (name, " ".join(texts)[:300]))
        if not texts:
            raise McpError("工具 %s 返回内容里没有 text" % name)
        return extract_payload("\n".join(texts))

    # ---------- 生命周期 ----------

    def __enter__(self) -> "McpClient":
        self.initialize()
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None
