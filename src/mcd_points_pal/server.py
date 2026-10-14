"""本地 Web 服务：把积分宝跑成一个能真正使用的应用。

    python3 -m mcd_points_pal serve

只监听 127.0.0.1，不对外暴露。Token 有两种给法：
  1. 启动前 `export MCD_MCP_TOKEN=...`
  2. 启动后在页面里粘贴（只存在进程内存里，不写任何文件）

路由：
    GET  /                  → 应用页面
    GET  /api/status        → 当前模式、门店、采集时间
    POST /api/token         → 设置 Token（内存；传空即改回离线快照）
    GET  /api/stores        → 按城市/关键词搜真实门店
    POST /api/store         → 选定门店
    GET  /api/catalog       → 菜单 + 积分券 + 积分账户（一次取齐）
    GET  /api/coupon?id=    → 券详情（官方兑换说明）
    POST /api/plan          → 账目推演 + 推荐
    POST /api/quote         → 真实核价（calculate-price）

安全边界：本服务不提供任何下单接口。
"""

from __future__ import annotations

import json
import os
import threading
import webbrowser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Dict, Optional, Tuple
from urllib.parse import parse_qs, urlparse

from .mcp_client import McpError
from .service import FORBIDDEN_TOOLS, Service, ServiceError

WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_BODY = 256 * 1024

MIME = {
    ".html": "text/html; charset=utf-8",
    ".js": "application/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
}


class Handler(BaseHTTPRequestHandler):
    service: Service = None  # 由 serve() 注入
    server_version = "mcd-points-pal"

    # ------------------------------------------------------------- 输出

    def log_message(self, fmt: str, *args: Any) -> None:
        # 默认日志太吵：只保留错误
        if args and str(args[1]).startswith(("4", "5")):
            super().log_message(fmt, *args)

    def _json(self, payload: Any, status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _fail(self, message: str, status: int = 400) -> None:
        self._json({"ok": False, "error": message}, status)

    def _body(self) -> Dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        if length <= 0:
            return {}
        if length > MAX_BODY:
            raise ServiceError("请求体过大。")
        raw = self.rfile.read(length)
        try:
            parsed = json.loads(raw.decode("utf-8") or "{}")
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ServiceError("请求体不是合法 JSON。")
        return parsed if isinstance(parsed, dict) else {}

    def _static(self, relative: str) -> None:
        target = (WEB_DIR / relative).resolve()
        if not str(target).startswith(str(WEB_DIR.resolve())) or not target.is_file():
            self._fail("找不到资源：%s" % relative, 404)
            return
        body = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", MIME.get(target.suffix, "application/octet-stream"))
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    # ------------------------------------------------------------- 路由

    def do_GET(self) -> None:  # noqa: N802
        parsed = urlparse(self.path)
        path = parsed.path
        query = parse_qs(parsed.query)
        try:
            if path in ("/", "/index.html"):
                self._static("index.html")
            elif path.startswith("/api/"):
                self._api_get(path, query)
            else:
                self._static(path.lstrip("/"))
        except (ServiceError, McpError) as exc:
            self._fail(str(exc))
        except Exception as exc:  # pragma: no cover - 兜底，避免整个服务挂掉
            self._fail("服务内部错误：%s" % exc, 500)

    def do_POST(self) -> None:  # noqa: N802
        path = urlparse(self.path).path
        try:
            if path == "/api/token":
                self._api_token()
            elif path == "/api/store":
                self._api_store()
            elif path == "/api/plan":
                self._json({"ok": True, **self.service.plan(self._cart())})
            elif path == "/api/quote":
                self._json({"ok": True, **self.service.quote(self._cart())})
            else:
                self._fail("未知接口：%s" % path, 404)
        except (ServiceError, McpError) as exc:
            self._fail(str(exc))
        except Exception as exc:  # pragma: no cover
            self._fail("服务内部错误：%s" % exc, 500)

    def _api_get(self, path: str, query: Dict[str, Any]) -> None:
        if path == "/api/status":
            self._json({"ok": True, **self.service.status()})
        elif path == "/api/stores":
            city = (query.get("city") or [""])[0]
            keyword = (query.get("keyword") or [""])[0]
            be_type = int((query.get("beType") or ["1"])[0])
            search_type = 2 if city and keyword else 1
            self._json({"ok": True, "stores": self.service.locate(city, keyword, be_type, search_type)})
        elif path == "/api/catalog":
            self._json({"ok": True, **self.service.catalog()})
        elif path == "/api/coupon":
            spu = (query.get("id") or [""])[0]
            self._json({"ok": True, **self.service.coupon_detail(int(spu))})
        else:
            self._fail("未知接口：%s" % path, 404)

    def _api_token(self) -> None:
        token = str(self._body().get("token") or "").strip()
        if not token:
            # 传空即「改回离线快照」——只有放下权限的动作，没有提权风险
            self.service.set_token("")
            self._json({"ok": True, "mode": self.service.mode})
            return
        previous = self.service.token
        self.service.set_token(token)
        try:
            account = self.service._account()
        except (ServiceError, McpError) as exc:
            self.service.set_token(previous)
            self._fail("这个 Token 连不上麦当劳 MCP：%s" % exc)
            return
        self._json({"ok": True, "mode": self.service.mode, "available": round(account.available, 1)})

    def _api_store(self) -> None:
        body = self._body()
        code = str(body.get("code") or "").strip()
        if not code:
            self._fail("缺少门店编码。")
            return
        self.service.set_store(
            code,
            name=str(body.get("name") or ""),
            be_type=int(body.get("beType") or 1),
            be_code=body.get("beCode") or None,
            distance=body.get("distance"),
        )
        self._json({"ok": True, **self.service.status()})

    def _cart(self) -> Dict[str, int]:
        raw = self._body().get("cart") or {}
        if not isinstance(raw, dict):
            raise ServiceError("cart 必须是 {商品编码: 数量} 的对象。")
        cart: Dict[str, int] = {}
        for key, value in raw.items():
            try:
                qty = int(value)
            except (TypeError, ValueError):
                raise ServiceError("数量不是整数：%s" % key)
            if qty > 0:
                cart[str(key)] = qty
        return cart


def serve(
    token: Optional[str] = None,
    host: str = "127.0.0.1",
    port: int = 8765,
    open_browser: bool = True,
    store_code: Optional[str] = None,
    be_type: int = 1,
    fixtures: Optional[Path] = None,
) -> None:
    service = Service(
        token=token or os.environ.get("MCD_MCP_TOKEN"),
        fixtures=fixtures,
        store_code=store_code,
        be_type=be_type,
    )
    Handler.service = service

    httpd = ThreadingHTTPServer((host, port), Handler)
    url = "http://%s:%d/" % (host, port)

    print("")
    print("  积分宝 · 本地应用已启动")
    print("  " + "=" * 52)
    print("    地址：   %s" % url)
    print("    数据源： %s" % ("麦当劳 MCP（实时）" if service.token else "离线快照（未配置 Token）"))
    if not service.token:
        print("    提示：   在页面顶部填入 MCP Token 即可切换为实时数据")
    print("    停止：   Ctrl+C")
    print("")

    if open_browser:
        threading.Timer(0.6, lambda: webbrowser.open(url)).start()

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n  已停止。\n")
    finally:
        httpd.server_close()
