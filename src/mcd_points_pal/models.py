"""积分宝 · 把麦当劳积分券搬进点餐流程。

核心数据模型。所有字段都对应麦当劳 MCP 的真实返回字段，命名保持一致，
方便和接口文档对照。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class ReferenceItem:
    """对照餐品：用现金买这份券里包含的东西，要花多少钱。"""

    product_code: Optional[str]
    product_name: str
    unit_price: float
    qty: int = 1

    @property
    def subtotal(self) -> float:
        return round(self.unit_price * self.qty, 2)


@dataclass
class Coupon:
    """一张积分兑换券。

    对应 MCP `mall-points-products` 返回的一条 data。
    `reference_*` 字段不是接口字段，来自 fixtures/coupon_reference.json 的人工核价表。
    """

    spu_id: int
    name: str
    points: int
    price: float
    image: str = ""
    up_time: str = ""
    down_time: str = ""
    status: int = 2
    cat_name: str = ""
    selling: str = ""

    reference_items: List[ReferenceItem] = field(default_factory=list)
    reference_total: Optional[float] = None
    reference_source: str = "unknown"

    @property
    def save(self) -> float:
        """省多少钱。没有对照价的券返回 0（不会参与排序推荐）。"""
        if self.reference_total is None:
            return 0.0
        return round(self.reference_total - self.price, 2)

    @property
    def efficiency(self) -> float:
        """每一分积分能省多少钱 —— 本项目排序的唯一依据。"""
        if not self.points or self.reference_total is None:
            return 0.0
        return round(self.save / self.points, 6)

    @property
    def priced(self) -> bool:
        """是否完成了交叉核价（有对照价）。"""
        return self.reference_total is not None


@dataclass
class Account:
    """积分账户。对应 MCP `query-my-account`。"""

    available: float
    accumulative: float = 0.0
    expiring_this_month: float = 0.0
    expired: float = 0.0
    used: float = 0.0
    currency: str = "麦享会积分"

    @classmethod
    def from_mcp(cls, data: Dict[str, Any]) -> "Account":
        def f(key: str) -> float:
            try:
                return float(data.get(key) or 0)
            except (TypeError, ValueError):
                return 0.0

        return cls(
            available=f("availablePoint"),
            accumulative=f("accumulativePoint"),
            expiring_this_month=f("currentMouthExpirePoint"),
            expired=f("expiredPoint"),
            used=f("usedPoint"),
            currency=data.get("currency") or "麦享会积分",
        )


@dataclass
class MenuProduct:
    product_code: str
    product_name: str
    price: float
    original_price: float = 0.0
    image: str = ""
    tags: List[str] = field(default_factory=list)

    @property
    def discount(self) -> float:
        return round(max(self.original_price - self.price, 0.0), 2)


@dataclass
class Menu:
    store_code: str
    store_name: str
    products: Dict[str, MenuProduct] = field(default_factory=dict)
    categories: List[Dict[str, Any]] = field(default_factory=list)

    def get(self, code: str) -> Optional[MenuProduct]:
        return self.products.get(str(code))


@dataclass
class OrderLine:
    """购物车里的一行。`kind` 为 'meal' 或 'coupon'。"""

    key: str
    name: str
    qty: int
    cash: float = 0.0
    points: int = 0
    reference_total: float = 0.0
    kind: str = "meal"

    @property
    def cash_total(self) -> float:
        return round(self.cash * self.qty, 2)

    @property
    def points_total(self) -> int:
        return self.points * self.qty

    @property
    def reference_total_all(self) -> float:
        return round(self.reference_total * self.qty, 2)


@dataclass
class CartSummary:
    lines: List[OrderLine]
    cash: float
    points_used: int
    reference_total: float
    earn_estimate: int = 0

    @property
    def saved(self) -> float:
        return round(self.reference_total - self.cash, 2)

    @property
    def item_count(self) -> int:
        return sum(l.qty for l in self.lines)
