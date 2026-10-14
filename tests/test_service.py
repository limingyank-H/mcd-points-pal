"""应用服务层与本地服务的测试。

快照模式下可以完整断言；真实 MCP 的调用只做协议级验证（见 test_mcp_client.py）。
"""

from __future__ import annotations

import json
import threading
import urllib.request
from http.server import ThreadingHTTPServer

import pytest

from mcd_points_pal.mcp_client import McpError, extract_payload
from mcd_points_pal.server import Handler, serve  # noqa: F401  (serve 确保导入不炸)
from mcd_points_pal.service import FORBIDDEN_TOOLS, Service, ServiceError

STORE = "1420888"


@pytest.fixture()
def service() -> Service:
    s = Service()
    assert s.mode == "snapshot"
    assert s.store_code == STORE, "快照模式应当自动摆上快照门店，别让用户卡在第一步"
    return s


# ---------------------------------------------------------------- 基础

def test_snapshot_service_is_readonly():
    assert "create-order" in FORBIDDEN_TOOLS
    assert "mall-create-order" in FORBIDDEN_TOOLS


def test_snapshot_cannot_call_real_mcp(service):
    with pytest.raises(ServiceError):
        service.locate("深圳", "科技园")


def test_status_reports_mode_and_store(service):
    status = service.status()
    assert status["mode"] == "snapshot"
    assert status["store"]["code"] == STORE
    assert status["snapshotTime"]


# ---------------------------------------------------------------- 目录

def test_catalog_shape(service):
    data = service.catalog()
    assert data["mode"] == "snapshot"
    assert data["store"]["code"] == STORE
    assert len(data["categories"]) >= 10
    assert len(data["products"]) > 50
    assert len(data["coupons"]) == 9
    assert data["staleCount"] == 15, "24 张券里 15 张是假上架，这个数有测试钉着"

    account = data["account"]
    assert account["available"] == 536.8
    assert account["expiringThisMonth"] == 91.0


def test_coupons_ranked_by_efficiency(service):
    coupons = service.catalog()["coupons"]
    efficiencies = [c["efficiency"] for c in coupons]
    assert efficiencies == sorted(efficiencies, reverse=True)
    assert coupons[0]["name"] == "6.9元可乐麦炫酷"
    assert coupons[-1]["name"] == "3.9元圆筒冰淇淋"


def test_unaffordable_coupons_flagged(service):
    for coupon in service.catalog()["coupons"]:
        assert coupon["affordable"] == (coupon["points"] <= 536.8)


def test_reference_refresh_uses_store_prices(service):
    """对照价必须跟着门店菜单走，而不是写死在核价表里。"""
    data = service.catalog()
    by_name = {c["name"]: c for c in data["coupons"]}
    row = by_name["6.9元可乐麦炫酷"]
    assert row["referenceSource"] == "menu"
    assert row["worth"] == pytest.approx(13.5)   # 本店「阳光橙麦炫酷」实时价
    assert row["save"] == pytest.approx(6.6)


# ---------------------------------------------------------------- 账目

def test_plan_matches_cli_numbers(service):
    plan = service.plan({"9900005456": 1, "P17078": 1})
    assert plan["referenceTotal"] == 62.5
    assert plan["cash"] == 50.4
    assert plan["saved"] == 12.1
    assert plan["pointsUsed"] == 200
    assert plan["earn"] == 50
    assert plan["balanceAfter"] == 386.8
    assert plan["nextGoal"]["name"] == "16.9元麦辣可乐组合"
    assert plan["nextGoal"]["gap"] == 113.2
    assert plan["ordersUntilNext"] == 3


def test_plan_marks_coupon_lines(service):
    plan = service.plan({"9900005456": 1, "P17078": 1})
    kinds = {(l["key"], l["kind"]) for l in plan["lines"]}
    assert ("9900005456", "meal") in kinds
    assert ("P17078", "coupon") in kinds


def test_plan_rejects_unknown_product(service):
    with pytest.raises((ServiceError, KeyError)):
        service.plan({"999999999999": 1})


def test_plan_rejects_empty_cart(service):
    with pytest.raises(ServiceError):
        service.plan({})


def test_quote_in_snapshot_mode_is_labelled(service):
    quote = service.quote({"9900005456": 1, "P17078": 1})
    assert quote["official"] is False
    assert quote["mealTotal"] == 33.5
    assert quote["couponCash"] == 16.9
    assert "不是官方核价" in quote["note"]


def test_quote_requires_a_real_meal(service):
    with pytest.raises(ServiceError):
        service.quote({"P17078": 1})


# ---------------------------------------------------------------- 服务路由

class _Server:
    def __init__(self, service: Service):
        Handler.service = service
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        self.url = "http://127.0.0.1:%d" % self.httpd.server_address[1]
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()

    def get(self, path: str, as_json: bool = True):
        with urllib.request.urlopen(self.url + path, timeout=10) as r:
            body = r.read().decode("utf-8")
            return r.status, (json.loads(body) if as_json else body)

    def post(self, path: str, body: dict):
        request = urllib.request.Request(
            self.url + path,
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=10) as r:
                return r.status, json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:  # noqa: F821
            return exc.code, json.loads(exc.read().decode("utf-8"))


@pytest.fixture()
def server():
    s = _Server(Service())
    yield s
    s.httpd.shutdown()


def test_server_serves_the_app(server):
    status, html = server.get("/", as_json=False)
    assert status == 200
    assert "积分宝" in html and "积分兑换" in html


def test_server_status_endpoint(server):
    _status, payload = server.get("/api/status")
    assert payload["ok"] is True
    assert payload["mode"] == "snapshot"
    assert payload["store"]["code"] == STORE


def test_server_catalog_endpoint(server):
    _status, payload = server.get("/api/catalog")
    assert payload["ok"] is True
    assert len(payload["coupons"]) == 9


def test_server_plan_endpoint(server):
    _status, payload = server.post("/api/plan", {"cart": {"9900005456": 1, "P17078": 1}})
    assert payload["ok"] is True
    assert payload["cash"] == 50.4


def test_server_rejects_bad_cart(server):
    status, payload = server.post("/api/plan", {"cart": {"nope!": 0}})
    assert status == 400
    assert payload["ok"] is False


def test_server_does_not_expose_ordering(server):
    """下单接口必须不存在 —— 这是合规底线。"""
    for path in ("/api/order", "/api/create-order", "/api/checkout-order"):
        status, _ = server.post(path, {"cart": {"9900005456": 1}})
        assert status == 404, path


def test_server_unknown_path_is_404(server):
    status, _ = server.post("/api/whatever", {})
    assert status == 404


# ---------------------------------------------------------------- 协议解析回归

def test_extract_payload_survives_document_notation():
    """门店搜索的说明段里有 `data[].storeName`，早先版本会把它当成 JSON 数组解析成 []。"""
    text = (
        "每个门店的基本信息按单行展示：\n"
        "- **门店名称**: data[].storeName\n"
        "- **到店距离**: data[].distance\n"
        '{"success":true,"code":200,"data":[{"storeCode":"1420762","storeName":"A"}]}'
        "## 展示结果时，每个门店的 storeCode 必须完整展示，\n"
    )
    payload = extract_payload(text)
    assert isinstance(payload, dict)
    assert payload["data"][0]["storeCode"] == "1420762"


def test_extract_payload_skips_placeholder_braces():
    """券详情说明段里有 `{data.skuList[].skuId}`，不是合法 JSON，必须跳过。"""
    text = (
        "### SKU规格列表\n"
        "| {data.skuList[].skuId} | {data.skuList[].points} |\n"
        '{"success":true,"data":{"spuId":17078,"skuList":[{"skuId":17784}]}}\n'
    )
    payload = extract_payload(text)
    assert payload["data"]["spuId"] == 17078


def test_extract_payload_still_handles_marker():
    text = "说明\n## Original Response\n" + json.dumps({"success": True, "data": {"ok": 1}})
    assert extract_payload(text)["data"]["ok"] == 1


def test_extract_payload_rejects_garbage():
    with pytest.raises(McpError):
        extract_payload("这里没有任何 JSON")
