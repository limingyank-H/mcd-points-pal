"""应用服务层：把「积分宝」做成一个能被前端直接调用的应用。

这一层的存在，是为了让产品不再是一个写死数据的原型：

    Service.locate("深圳", "科技园")   → 真实调 query-nearby-stores
    Service.select_store("1420888")    → 选定门店
    Service.catalog()                  → query-meals + mall-points-products + query-my-account
    Service.plan(cart)                 → 账目推演 + 推荐 + 下一次目标
    Service.quote(cart)                → 真实调 calculate-price 核价

两种模式返回完全相同的结构，所以前端不需要知道数据是从哪来的：

  * live     —— 真实调用 mcp.mcd.cn（需要 Token）
  * snapshot —— 读 fixtures/ 里固化的真实响应，clone 即跑，界面上明确标注采集时间

安全边界：本服务**不会调用 create-order / mall-create-order**，
任何情况下都不会替用户下单。
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from .datasource import FIXTURES, FixtureSource, McpSource
from .models import Account, Coupon, Menu
from .planner import build_plan, efficiency_spread
from .points import affordable, next_goal, parse_coupons, rank, split_by_validity

# 允许被调用的 MCP 工具白名单：写死在这里，避免上层任何代码路径误调下单类接口。
READONLY_TOOLS = frozenset(
    [
        "query-nearby-stores",
        "query-meals",
        "query-meal-detail",
        "query-my-account",
        "query-store-coupons",
        "query-my-coupons",
        "mall-points-products",
        "mall-product-detail",
        "calculate-price",
        "now-time-info",
    ]
)

# 明确禁止：本项目的任何一层都不得调用它们。
FORBIDDEN_TOOLS = frozenset(
    ["create-order", "mall-create-order", "party-order-create", "cancel-order", "draw-lottery"]
)


class ServiceError(RuntimeError):
    """可以直接展示给用户的错误。"""


def _yuan(fen: Any) -> float:
    """calculate-price 的单位是「分」——踩过坑，这里显式转换。"""
    try:
        return round(float(fen) / 100.0, 2)
    except (TypeError, ValueError):
        return 0.0


class Service:
    def __init__(
        self,
        token: Optional[str] = None,
        fixtures: Optional[Path] = None,
        store_code: Optional[str] = None,
        store_name: str = "",
        be_type: int = 1,
        be_code: Optional[str] = None,
        cache_seconds: int = 120,
    ):
        self.token = (token or os.environ.get("MCD_MCP_TOKEN") or "").strip()
        self.fixtures = Path(fixtures) if fixtures else FIXTURES
        self.store_code = store_code
        self.store_name = store_name
        self.be_type = be_type
        self.be_code = be_code
        self.distance: Optional[int] = None
        self.cache_seconds = cache_seconds

        self._source = None
        self._cache: Dict[str, Tuple[float, Any]] = {}
        self._snapshot_time = self._read_snapshot_time()
        if not self.store_code and not self.token:
            # 快照模式没有门店搜索能力，直接把快照里的门店摆上，别让用户卡在第一步
            self.store_code, self.store_name = self._fixture_store()

    # ------------------------------------------------------------------ 模式

    @property
    def mode(self) -> str:
        return "live" if self.token else "snapshot"

    def _read_snapshot_time(self) -> str:
        path = self.fixtures / "my_account.json"
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            return str(payload.get("_capturedAt") or "")
        except (OSError, ValueError):
            return ""

    def _fixture_store(self) -> Tuple[Optional[str], str]:
        for path in sorted(self.fixtures.glob("menu_*.json")):
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            code = raw.get("storeCode")
            if code:
                return str(code), str(raw.get("storeName") or "")
        return None, ""

    @property
    def source(self):
        if self._source is None:
            if self.token:
                self._source = McpSource(
                    token=self.token,
                    store_code=self.store_code or "",
                    store_name=self.store_name,
                    be_type=self.be_type,
                    be_code=self.be_code,
                )
            else:
                self._source = FixtureSource(self.fixtures)
        return self._source

    def set_token(self, token: str) -> None:
        """换 Token 等于换数据源，缓存全部作废。"""
        self.token = (token or "").strip()
        self._source = None
        self._cache.clear()
        if not self.token:
            self.store_code = None
            self.store_name = ""

    def set_store(self, code: str, name: str = "", be_type: int = 1,
                  be_code: Optional[str] = None, distance: Optional[int] = None) -> None:
        self.store_code = str(code)
        self.store_name = name
        self.be_type = be_type
        self.be_code = be_code
        self.distance = distance
        if isinstance(self._source, McpSource):
            self._source.store_code = self.store_code
            self._source.store_name = name
            self._source.be_type = be_type
            self._source.be_code = be_code
        self._cache.clear()

    def _cached(self, key: str, producer):
        now = time.time()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.cache_seconds:
            return hit[1]
        value = producer()
        self._cache[key] = (now, value)
        return value

    # ------------------------------------------------------------------ 状态

    def status(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "hasToken": bool(self.token),
            "store": (
                {
                    "code": self.store_code,
                    "name": self.store_name,
                    "beType": self.be_type,
                    "beCode": self.be_code,
                    "distance": self.distance,
                }
                if self.store_code
                else None
            ),
            "snapshotTime": self._snapshot_time,
            "fixtures": str(self.fixtures),
            "serverTime": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }

    # ------------------------------------------------------------------ 门店

    def locate(self, city: str = "", keyword: str = "", be_type: int = 1,
               search_type: int = 2) -> List[Dict[str, Any]]:
        if not self.token:
            raise ServiceError(
                "离线快照模式下不能搜索真实门店。接入 Token 后即可按城市/商圈搜索你附近的麦当劳。"
            )
        args: Dict[str, Any] = {"beType": be_type, "searchType": search_type}
        if search_type == 2:
            if not city or not keyword:
                raise ServiceError("按位置搜索需要同时提供城市和关键词。")
            args["city"] = city
            args["keyword"] = keyword
        payload = self._call("query-nearby-stores", args)
        rows = payload.get("data") or []
        if not isinstance(rows, list):
            return []
        stores = []
        for row in rows:
            stores.append(
                {
                    "code": str(row.get("storeCode") or ""),
                    "name": row.get("storeName") or "",
                    "address": row.get("address") or "",
                    "distance": row.get("distance"),
                    "beType": be_type,
                    "beCode": row.get("beCode") or None,
                    "open": bool(row.get("businessStatus", True)),
                    "openTime": "%s-%s" % (row.get("businessStartTime") or "", row.get("businessEndTime") or ""),
                    "reservation": bool(row.get("reservation")),
                }
            )
        return stores

    # ------------------------------------------------------------------ 目录

    def catalog(self) -> Dict[str, Any]:
        """一次取齐：菜单 + 积分券 + 积分账户。前端一次请求就能出首屏。"""
        if not self.store_code:
            raise ServiceError("还没有选择门店。")
        menu = self._cached("menu:%s" % self.store_code, self._menu)
        account = self._cached("account", self._account)
        active, stale = self._cached("coupons", self._coupons)

        # 用门店实时菜单刷新「对照价」，让「省多少」跟着这家店的真实价格走
        refreshed = self._refreshed_coupons(active, menu)
        ranked = rank(refreshed)
        best, worst, ratio = efficiency_spread(refreshed)

        return {
            "mode": self.mode,
            "snapshotTime": self._snapshot_time,
            "store": {
                "code": self.store_code,
                "name": menu.store_name or self.store_name,
                "beType": self.be_type,
                "beCode": self.be_code,
                "distance": self.distance,
            },
            "account": {
                "available": round(account.available, 1),
                "expiringThisMonth": round(account.expiring_this_month, 1),
                "expired": round(account.expired, 1),
                "accumulative": round(account.accumulative, 1),
                "used": round(account.used, 1),
            },
            "categories": [{"name": c["name"], "products": c["products"]} for c in menu.categories],
            "products": {
                code: {
                    "code": p.product_code,
                    "name": p.product_name,
                    "price": p.price,
                    "originalPrice": p.original_price,
                    "image": p.image,
                    "tags": p.tags,
                }
                for code, p in menu.products.items()
            },
            "coupons": [
                {
                    "spuId": c.spu_id,
                    "name": c.name,
                    "points": c.points,
                    "cash": c.price,
                    "worth": c.reference_total,
                    "save": c.save,
                    "efficiency": c.efficiency,
                    "image": c.image,
                    "affordable": c.points <= account.available,
                    "referenceSource": c.reference_source,
                    "note": self._reference_note(c.spu_id),
                }
                for c in ranked
            ],
            "staleCount": len(stale),
            "unpricedCount": len([c for c in refreshed if not c.priced]),
            "efficiencySpread": {
                "ratio": ratio,
                "best": {"name": best.name, "efficiency": best.efficiency} if best else None,
                "worst": {"name": worst.name, "efficiency": worst.efficiency} if worst else None,
            },
        }

    def coupon_detail(self, spu_id: int) -> Dict[str, Any]:
        """券详情：真实调 mall-product-detail 拿兑换说明与 SKU。"""
        if not self.token:
            raise ServiceError("离线快照模式下没有券详情，接入 Token 后可查看官方兑换说明。")
        payload = self._call("mall-product-detail", {"spuId": int(spu_id)})
        data = payload.get("data") or {}
        skus = []
        for sku in data.get("skuList") or []:
            skus.append(
                {
                    "skuId": sku.get("skuId"),
                    "points": sku.get("points"),
                    "cash": sku.get("extTradePrice") or sku.get("price"),
                    "spec": " / ".join(
                        "%s：%s" % (s.get("specMain"), s.get("specItem"))
                        for s in (sku.get("specList") or [])
                    ),
                }
            )
        return {
            "spuId": data.get("spuId", spu_id),
            "name": data.get("spuName") or "",
            "image": (data.get("images") or [""])[0],
            "selling": data.get("selling") or "",
            "upTime": data.get("upTime") or "",
            "downTime": data.get("downTime") or "",
            # note 是官方原文，必须整段原样展示，不做二次加工
            "note": data.get("note") or "",
            "skus": skus,
        }

    # ------------------------------------------------------------------ 账目

    def plan(self, cart: Dict[str, int]) -> Dict[str, Any]:
        cart = {str(k): int(v) for k, v in (cart or {}).items() if int(v) > 0}
        if not cart:
            raise ServiceError("购物车是空的。")

        menu = self._cached("menu:%s" % self.store_code, self._menu)
        account = self._cached("account", self._account)
        active, _stale = self._cached("coupons", self._coupons)
        active = self._refreshed_coupons(active, menu)

        plan = build_plan(cart, active, menu, account)

        lines = [
            {
                "key": l.key,
                "name": l.name,
                "qty": l.qty,
                "cash": l.cash,
                "cashTotal": l.cash_total,
                "points": l.points,
                "kind": l.kind,
                "worth": l.reference_total,
            }
            for l in plan.summary.lines
        ]
        goal = plan.next_coupon
        return {
            "mode": self.mode,
            "lines": lines,
            "itemCount": plan.summary.item_count,
            "referenceTotal": round(plan.summary.reference_total, 2),
            "cash": round(plan.summary.cash, 2),
            "saved": round(plan.summary.saved, 2),
            "pointsUsed": plan.summary.points_used,
            "earn": plan.summary.earn_estimate,
            "balanceNow": round(account.available, 1),
            "balanceAfter": plan.balance_after,
            "expiringThisMonth": round(account.expiring_this_month, 1),
            "recommended": [
                {
                    "spuId": c.spu_id,
                    "name": c.name,
                    "points": c.points,
                    "cash": c.price,
                    "worth": c.reference_total,
                    "save": c.save,
                    "efficiency": c.efficiency,
                    "image": c.image,
                }
                for c in plan.recommended
            ],
            "nextGoal": (
                {
                    "spuId": goal.spu_id,
                    "name": goal.name,
                    "points": goal.points,
                    "gap": round(goal.points - plan.balance_after, 1),
                }
                if goal
                else None
            ),
            "ordersUntilNext": plan.orders_until_next,
        }

    def quote(self, cart: Dict[str, int]) -> Dict[str, Any]:
        """真实核价：调 calculate-price。

        积分券走的是「卡包券」通道（couponId/couponCode），不能当商品编码传；
        这里只对普通餐品做官方核价，券的现金价来自券面价，两部分分别列出，不混算。
        """
        cart = {str(k): int(v) for k, v in (cart or {}).items() if int(v) > 0}
        meals = {k: v for k, v in cart.items() if not k.startswith("P")}
        coupon_keys = {k: v for k, v in cart.items() if k.startswith("P")}
        if not meals:
            raise ServiceError("真实核价需要至少一件普通餐品（积分券要随单核销，不能单独核价）。")

        menu = self._cached("menu:%s" % self.store_code, self._menu)
        items = []
        for key, qty in meals.items():
            if menu.get(key) is None:
                raise ServiceError("餐品 %s 不在本店菜单里，无法核价。" % key)
            items.append({"productCode": str(key), "quantity": int(qty)})

        if not self.token:
            # 快照模式：用菜单价合计，并明确标注这不是官方核价
            total = round(sum(menu.get(k).price * v for k, v in meals.items()), 2)
            return {
                "official": False,
                "mode": self.mode,
                "mealTotal": total,
                "couponCash": self._coupon_cash(coupon_keys),
                "note": "离线快照模式：金额取自快照菜单价，不是官方核价。",
            }

        args: Dict[str, Any] = {
            "storeCode": self.store_code,
            "orderType": 1,
            "beType": self.be_type,
            "items": items,
        }
        # 到店自取不能带 beCode；得来速/外送必带。方向相反，最容易翻车。
        if self.be_type in (2, 5, 6):
            if not self.be_code:
                raise ServiceError("该门店类型必须带 beCode，请重新选择门店。")
            args["beCode"] = self.be_code

        payload = self._call("calculate-price", args)
        data = payload.get("data") or {}

        return {
            "official": True,
            "mode": self.mode,
            "mealTotal": _yuan(data.get("price")),
            "mealOriginal": _yuan(data.get("originalPrice")),
            "discount": _yuan(data.get("discount")),
            "couponCash": self._coupon_cash(coupon_keys),
            "productList": [
                {
                    "code": r.get("productCode"),
                    "name": r.get("productName"),
                    "qty": r.get("quantity"),
                    "subtotal": _yuan(r.get("subtotal")),
                }
                for r in (data.get("productList") or [])
            ],
            "takeWayList": [
                {"code": t.get("code"), "title": t.get("title"), "subtitle": t.get("subtitle")}
                for t in (data.get("takeWayList") or [])
            ],
            "note": "餐品价由麦当劳 calculate-price 实时返回；积分券现金价取自券面价。",
        }

    # ------------------------------------------------------------------ 底层

    def _call(self, name: str, args: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if name in FORBIDDEN_TOOLS:
            raise ServiceError("本项目不会调用 %s —— 下单必须由你在麦当劳官方渠道完成。" % name)
        if name not in READONLY_TOOLS:
            raise ServiceError("未授权的 MCP 工具：%s" % name)
        client = getattr(self.source, "client", None)
        if client is None:
            raise ServiceError("当前是离线快照模式，不能调用真实 MCP。")
        payload = client.call_tool(name, args or {})
        if isinstance(payload, dict) and payload.get("success") is False:
            raise ServiceError("%s 调用失败：%s" % (name, payload.get("message")))
        return payload if isinstance(payload, dict) else {}

    def _menu(self) -> Menu:
        if self.token and isinstance(self._source, McpSource) and not self.store_name:
            menu = self._source.menu()
            if menu.store_name:
                self.store_name = menu.store_name
                self._source.store_name = menu.store_name
            return menu
        return self.source.menu()

    def _account(self) -> Account:
        return self.source.account()

    def _coupons(self) -> Tuple[List[Coupon], List[Coupon]]:
        return self.source.coupons()

    def _reference_for(self, menu: Menu) -> Dict[str, Any]:
        """核价表 + 门店实时价。有 productCode 且本店在售的，用实时价重算。"""
        try:
            table = json.loads((self.fixtures / "coupon_reference.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        reference = dict(table.get("reference") or {})
        out: Dict[str, Any] = {}
        for spu, row in reference.items():
            row = json.loads(json.dumps(row))
            items = row.get("referenceItems") or []
            hit = False
            for item in items:
                code = item.get("productCode")
                product = menu.get(code) if code else None
                if product is not None and product.price > 0:
                    item["unitPrice"] = product.price
                    hit = True
            if hit and items:
                row["referenceTotal"] = round(sum(float(i.get("unitPrice", 0)) * int(i.get("qty", 1)) for i in items), 2)
                row["referenceSource"] = "menu-live" if self.token else "menu"
            out[spu] = row
        return out

    def _refreshed_coupons(self, active: List[Coupon], menu: Menu) -> List[Coupon]:
        """把券重新按门店实时菜单核价。

        刷新失败（对照餐品本店没有、或价格取不到）就退回原核价表的值 —— 
        宁可保留一个旧的对照价，也不要让它变成 0 而混进效率榜。
        """
        table = self._reference_for(menu)
        refreshed = parse_coupons(
            {"data": [{"spuId": c.spu_id, "spuName": c.name, "point": c.points,
                       "price": c.price, "spuImage": c.image, "upTime": c.up_time,
                       "downTime": c.down_time, "status": c.status,
                       "catName": c.cat_name, "selling": c.selling} for c in active]},
            {"reference": table},
        )
        by_id = {c.spu_id: c for c in active}
        for coupon in refreshed:
            old = by_id.get(coupon.spu_id)
            if old and coupon.reference_total is None:
                coupon.reference_items = old.reference_items
                coupon.reference_total = old.reference_total
                coupon.reference_source = old.reference_source
        return refreshed or active

    def _coupon_by_spu(self, spu_id: int) -> Optional[Coupon]:
        active, _stale = self._cached("coupons", self._coupons)
        for coupon in active:
            if coupon.spu_id == spu_id:
                return coupon
        return None

    def _coupon_cash(self, coupon_keys: Dict[str, int]) -> float:
        """购物车里积分券要付的现金合计（券面价 × 数量）。"""
        total = 0.0
        for key, qty in coupon_keys.items():
            try:
                spu_id = int(str(key)[1:])
            except ValueError:
                continue
            coupon = self._coupon_by_spu(spu_id)
            if coupon is not None:
                total += coupon.price * qty
        return round(total, 2)

    def _reference_note(self, spu_id: int) -> str:
        payload = self._reference_for(self._cached("menu:%s" % self.store_code, self._menu))
        return (payload.get(str(spu_id)) or {}).get("note") or ""
