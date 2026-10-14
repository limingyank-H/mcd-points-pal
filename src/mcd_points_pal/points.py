"""积分券的清洗与排序 —— 本项目的方法学所在。

MCP 只告诉我们「有哪些券」。至于「哪张券值得换」，需要我们自己算：
   1. 过滤掉 downTime 已过、但 status 仍为 2（上架）的「假上架」券
   2. 为每张券找到现金对照价（用门店菜单的单点价）
   3. 按「每积分省多少钱」排序

第 2 步是唯一带主观判断的地方，所以它的输入被显式写进
fixtures/coupon_reference.json，可逐条审计。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional, Tuple

from .models import Coupon, ReferenceItem

TIME_FORMATS = ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d")


def parse_time(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(value.strip(), fmt)
        except ValueError:
            continue
    return None


def money(value: float) -> str:
    return "¥%.2f" % value


def money4(value: float) -> str:
    """每积分效率要 4 位小数——2 位会把 12 倍的差距抹平。"""
    return "¥%.4f" % value


def _reference(raw: Dict[str, Any]) -> Tuple[List[ReferenceItem], Optional[float], str]:
    items = [
        ReferenceItem(
            product_code=it.get("productCode"),
            product_name=it.get("productName", ""),
            unit_price=float(it.get("unitPrice", 0)),
            qty=int(it.get("qty", 1)),
        )
        for it in raw.get("referenceItems", [])
    ]
    total = raw.get("referenceTotal")
    return items, (float(total) if total is not None else None), raw.get("referenceSource", "unknown")


def parse_coupons(
    payload: Dict[str, Any],
    reference: Optional[Dict[str, Any]] = None,
) -> List[Coupon]:
    """把 `mall-points-products` 的原始响应转成 Coupon 列表。"""
    table = (reference or {}).get("reference") or reference or {}
    rows = payload.get("data") if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError("券列表格式不正确：期望 data 为数组")

    coupons: List[Coupon] = []
    for row in rows:
        try:
            spu_id = int(row.get("spuId"))
        except (TypeError, ValueError):
            continue
        ref = table.get(str(spu_id), {}) or {}
        items, total, source = _reference(ref)
        price_text = str(ref.get("price") if ref.get("price") is not None else 0)
        # 券面现金价优先取核价表（券名里的数字），其次取接口 price 字段
        if not ref:
            price_text = str(row.get("price") or 0)
        try:
            price = float(price_text)
        except (TypeError, ValueError):
            price = 0.0

        coupons.append(
            Coupon(
                spu_id=spu_id,
                name=(row.get("spuName") or "").strip(),
                points=int(float(row.get("point") or 0)),
                price=price,
                image=row.get("spuImage") or "",
                up_time=row.get("upTime") or "",
                down_time=row.get("downTime") or "",
                status=int(row.get("status") or 0),
                cat_name=row.get("catName") or "",
                selling=(row.get("selling") or "").strip(),
                reference_items=items,
                reference_total=total,
                reference_source=source,
            )
        )
    return coupons


def split_by_validity(
    coupons: Iterable[Coupon], now: Optional[datetime] = None
) -> Tuple[List[Coupon], List[Coupon]]:
    """返回 (有效券, 假上架券)。

    判定规则：`downTime` 早于当前时间，或状态不是「上架(2)」，
    一律视为不可兑换 —— 即使接口把它标成上架。
    """
    now = now or datetime.now()
    active: List[Coupon] = []
    stale: List[Coupon] = []
    for coupon in coupons:
        deadline = parse_time(coupon.down_time)
        expired = deadline is not None and deadline < now
        if coupon.status == 2 and not expired:
            active.append(coupon)
        else:
            stale.append(coupon)
    return active, stale


def rank(coupons: Iterable[Coupon], priced_only: bool = True) -> List[Coupon]:
    """按每积分效率降序。没有对照价的券不参与排名（避免拿 0 混进来）。"""
    pool = [c for c in coupons if c.priced] if priced_only else list(coupons)
    return sorted(pool, key=lambda c: (-c.efficiency, -c.save, c.points))


def affordable(coupons: Iterable[Coupon], balance: float) -> List[Coupon]:
    return [c for c in coupons if c.points <= balance]


def next_goal(coupons: Iterable[Coupon], balance: float) -> Optional[Coupon]:
    """下一次目标：积分比当前余额高、且最接近的那一档券。"""
    candidates = [c for c in coupons if c.points > balance]
    if not candidates:
        return None
    return min(candidates, key=lambda c: (c.points - balance, c.points))
