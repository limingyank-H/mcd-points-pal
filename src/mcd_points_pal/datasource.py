"""数据源：真实 MCP 与离线 fixtures 共用同一套接口。

两种模式的意义：
  * McpSource     —— 真实调用 mcp.mcd.cn，需要 MCD_MCP_TOKEN
  * FixtureSource —— 读 fixtures/ 里固化下来的真实响应，clone 即跑，零配置

两者返回完全相同的模型对象，所以上层 planner / render 不需要知道
数据是从哪来的。这也是能对离线结果做断言测试的前提。
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .mcp_client import McpClient
from .models import Account, Coupon, Menu, MenuProduct, OrderLine
from .points import parse_coupons, split_by_validity

REPO_ROOT = Path(__file__).resolve().parents[2]
FIXTURES = REPO_ROOT / "fixtures"

# 随单购 / 麦金卡这类优惠价，只有在用户额外购买会员卡时才成立。
# 做成本对比时必须用不依赖会员卡的常规价，否则会把「省」算虚。
CONDITIONAL_DISCOUNT = ("随单购",)


def _load(name: str) -> Dict[str, Any]:
    path = FIXTURES / name
    if not path.exists():
        raise FileNotFoundError("缺少 fixture：%s" % path)
    with path.open(encoding="utf-8") as fh:
        return json.load(fh)


def _reference_table() -> Dict[str, Any]:
    return _load("coupon_reference.json").get("reference", {})


def normalize_menu(payload: Dict[str, Any], store_code: str, store_name: str) -> Menu:
    """把 `query-meals` 的响应转成 Menu。

    真实结构（已核对）：
        data.categories[].name
        data.categories[].meals[].code / .tags
        data.meals[code].name / .image / .currentPrice / .originalPrice
    """
    data = payload.get("data") or {}
    raw_meals: Dict[str, Any] = data.get("meals") or {}
    categories: List[Dict[str, Any]] = []

    for category in data.get("categories") or []:
        codes = []
        for item in category.get("meals") or []:
            code = item.get("code") or item.get("productCode")
            if code is not None:
                codes.append(str(code))
        categories.append({"name": category.get("name") or "", "products": codes})

    products: Dict[str, MenuProduct] = {}
    for code, item in raw_meals.items():
        if not isinstance(item, dict):
            continue
        try:
            price = float(item.get("currentPrice") or 0)
        except (TypeError, ValueError):
            price = 0.0
        try:
            original = float(item.get("originalPrice") or price)
        except (TypeError, ValueError):
            original = price
        discount_type = item.get("discountType") or ""
        tags = []
        if discount_type:
            tags.append(discount_type)
        if any(flag in discount_type for flag in CONDITIONAL_DISCOUNT):
            tags.append("需随单购")
        products[str(code)] = MenuProduct(
            product_code=str(code),
            product_name=(item.get("name") or "").strip(),
            price=price,
            original_price=original,
            image=item.get("image") or "",
            tags=tags,
        )

    return Menu(store_code=store_code, store_name=store_name, products=products, categories=categories)


class FixtureSource:
    """离线数据源：全部来自 fixtures/ 内固化的真实 MCP 响应。"""

    mode = "fixture"

    def __init__(self, fixtures: Optional[Path] = None):
        self.dir = Path(fixtures) if fixtures else FIXTURES

    def _load(self, name: str) -> Dict[str, Any]:
        with (self.dir / name).open(encoding="utf-8") as fh:
            return json.load(fh)

    def reference(self) -> Dict[str, Any]:
        return self._load("coupon_reference.json").get("reference", {})

    def account(self) -> Account:
        return Account.from_mcp(self._load("my_account.json").get("data") or {})

    def coupon_payload(self) -> Dict[str, Any]:
        return self._load("points_products.json")

    def coupons(self, now=None) -> Tuple[List[Coupon], List[Coupon]]:
        all_coupons = parse_coupons(self.coupon_payload(), {"reference": self.reference()})
        return split_by_validity(all_coupons, now)

    def menu(self) -> Menu:
        raw = self._load("menu_1420888.json")
        products = {
            str(p["productCode"]): MenuProduct(
                product_code=str(p["productCode"]),
                product_name=p["productName"],
                price=float(p["price"]),
                original_price=float(p.get("originalPrice") or p["price"]),
                image=p.get("image") or "",
                tags=list(p.get("tags") or []),
            )
            for p in raw.get("products", [])
        }
        return Menu(
            store_code=str(raw.get("storeCode") or ""),
            store_name=raw.get("storeName") or "",
            products=products,
            categories=[
                {"name": c.get("name", ""), "products": [str(x) for x in c.get("products", [])]}
                for c in raw.get("categories", [])
            ],
        )

    def orders(self) -> List[Dict[str, Any]]:
        return (self._load("orders.json").get("data") or {}).get("list") or []


class McpSource:
    """真实数据源：直连麦当劳 MCP。"""

    mode = "mcp"

    def __init__(
        self,
        token: Optional[str] = None,
        store_code: str = "1420888",
        store_name: str = "",
        be_type: int = 1,
        order_type: int = 1,
        be_code: Optional[str] = None,
        url: Optional[str] = None,
    ):
        self.token = token or os.environ.get("MCD_MCP_TOKEN") or ""
        self.store_code = store_code
        self.store_name = store_name
        self.be_type = be_type
        self.order_type = order_type
        self.be_code = be_code
        self.url = url or os.environ.get("MCD_MCP_URL")
        self._client: Optional[McpClient] = None
        self._session_id = None

    # ---- 连接 ----

    @property
    def client(self) -> McpClient:
        if self._client is None:
            kwargs = {"token": self.token}
            if self.url:
                kwargs["url"] = self.url
            client = McpClient(**kwargs)
            client.initialize()
            self._client = client
        return self._client

    def close(self) -> None:
        self._client = None

    def __enter__(self) -> "McpSource":
        self.client
        return self

    def __exit__(self, *_exc: Any) -> None:
        self.close()

    # ---- 数据 ----

    def reference(self) -> Dict[str, Any]:
        # 对照价不是接口字段，仍需本地核价表 —— 这一步是方法学的一部分，不是偷懒。
        return _reference_table()

    def account(self) -> Account:
        payload = self.client.call_tool("query-my-account")
        if not payload.get("success", True):
            raise RuntimeError("query-my-account 失败：%s" % payload.get("message"))
        return Account.from_mcp(payload.get("data") or {})

    def coupon_payload(self) -> Dict[str, Any]:
        return self.client.call_tool("mall-points-products", {"catRuleIds": "1>4"})

    def coupons(self, now=None) -> Tuple[List[Coupon], List[Coupon]]:
        all_coupons = parse_coupons(self.coupon_payload(), {"reference": self.reference()})
        return split_by_validity(all_coupons, now)

    def menu(self) -> Menu:
        args: Dict[str, Any] = {
            "storeCode": self.store_code,
            "orderType": self.order_type,
            "beType": self.be_type,
        }
        # 外送 / 得来速 / 团餐场景必须带 beCode；到店自取带了反而报错。
        if self.be_type in (2, 5, 6):
            if not self.be_code:
                raise ValueError("beType=%s 时必须提供 beCode" % self.be_type)
            args["beCode"] = self.be_code
        payload = self.client.call_tool("query-meals", args)
        if not payload.get("success", True):
            raise RuntimeError("query-meals 失败：%s" % payload.get("message"))
        return normalize_menu(payload, self.store_code, self.store_name)

    def orders(self) -> List[Dict[str, Any]]:
        payload = self.client.call_tool("order-list")
        return (payload.get("data") or {}).get("list") or []
