"""推荐引擎：把券、菜单、账户拼成一条可以照着做的建议。

设计边界（写进 README，也写进 SKILL.md）：
  * 只算不劝 —— 输出「省多少」，不替用户决定用哪张
  * 定价权交给用户 —— 积分余额来自用户自己的账户，不假设他的消费水平
  * 不贬低品牌 —— 不出现「不健康」「不值」类表述
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

from .models import Account, CartSummary, Coupon, Menu, OrderLine
from .points import affordable, next_goal, rank

COUPON_PREFIX = "P"

# 消费积分规则：¥1 = 1 分。这里只做「本单预计可得」的示意估算，
# 真实入账以麦当劳官方结算为准。
DEFAULT_EARN_RATE = 1.0


def parse_cart(spec: str) -> Dict[str, int]:
    """解析 `--cart 1100:1,9900005456:2,P17078:1`。

    普通餐品用 productCode，积分券用 `P` + spuId。
    """
    cart: Dict[str, int] = {}
    if not spec:
        return cart
    for chunk in spec.replace(";", ",").split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" in chunk:
            key, _, qty = chunk.partition(":")
        else:
            key, qty = chunk, "1"
        key = key.strip()
        try:
            count = int(qty.strip() or 1)
        except ValueError:
            raise ValueError("数量不是整数：%s" % chunk)
        if count <= 0:
            raise ValueError("数量必须大于 0：%s" % chunk)
        cart[key] = cart.get(key, 0) + count
    return cart


def coupon_id_of(key: str) -> Optional[int]:
    if not key.startswith(COUPON_PREFIX):
        return None
    try:
        return int(key[len(COUPON_PREFIX):])
    except ValueError:
        return None


def build_summary(
    cart: Dict[str, int],
    coupons: Iterable[Coupon],
    menu: Menu,
    earn_rate: float = DEFAULT_EARN_RATE,
) -> CartSummary:
    """把购物车算成账：实付现金、消耗积分、以及「如果原价买要花多少」。

    注意区分两个概念：
      cash            —— 这单实际要付的现金
      reference_total —— 同样的东西不用券要花多少（券价 + 对照价）
    差额才是「省」。
    """
    by_id = {c.spu_id: c for c in coupons}
    lines: List[OrderLine] = []
    cash = 0.0
    points = 0
    reference = 0.0

    for key, qty in cart.items():
        spu = coupon_id_of(key)
        if spu is not None:
            coupon = by_id.get(spu)
            if coupon is None:
                raise KeyError(
                    "购物车里的券 P%s 不在当前有效券列表里（可能已过期或不在本店可兑换范围）" % spu
                )
            ref = coupon.reference_total if coupon.reference_total is not None else coupon.price
            lines.append(
                OrderLine(
                    key=key,
                    name=coupon.name,
                    qty=qty,
                    cash=coupon.price,
                    points=coupon.points,
                    reference_total=ref,
                    kind="coupon",
                )
            )
            cash += coupon.price * qty
            points += coupon.points * qty
            reference += ref * qty
            continue

        product = menu.get(key)
        if product is None:
            raise KeyError(
                "餐品 %s 不在门店 %s 的菜单里（可能已下架——"
                "calculate-price 对失效编码是静默丢弃的）" % (key, menu.store_code)
            )
        lines.append(
            OrderLine(
                key=key,
                name=product.product_name,
                qty=qty,
                cash=product.price,
                points=0,
                reference_total=product.price,
                kind="meal",
            )
        )
        cash += product.price * qty
        reference += product.price * qty

    cash = round(cash, 2)
    return CartSummary(
        lines=lines,
        cash=cash,
        points_used=points,
        reference_total=round(reference, 2),
        earn_estimate=int(cash * earn_rate),
    )


@dataclass
class Plan:
    """一份可以直接念给用户听的建议。"""

    summary: CartSummary
    account: Account
    recommended: List[Coupon] = field(default_factory=list)
    balance_after: float = 0.0
    next_coupon: Optional[Coupon] = None
    orders_until_next: Optional[int] = None
    unpriced: List[Coupon] = field(default_factory=list)

    @property
    def saved(self) -> float:
        return self.summary.saved


def build_plan(
    cart: Dict[str, int],
    active_coupons: Sequence[Coupon],
    menu: Menu,
    account: Account,
    limit: int = 3,
) -> Plan:
    summary = build_summary(cart, active_coupons, menu)
    chosen = {coupon_id_of(k) for k in cart if coupon_id_of(k) is not None}

    pool = [c for c in affordable(active_coupons, account.available) if c.spu_id not in chosen]
    recommended = rank(pool)[:limit]

    balance_after = round(account.available - summary.points_used + summary.earn_estimate, 1)
    goal = next_goal(active_coupons, balance_after)

    orders = None
    if goal is not None and summary.earn_estimate > 0:
        gap = goal.points - balance_after
        orders = int(-(-gap // summary.earn_estimate))  # 向上取整

    unpriced = [c for c in active_coupons if not c.priced]

    return Plan(
        summary=summary,
        account=account,
        recommended=recommended,
        balance_after=balance_after,
        next_coupon=goal,
        orders_until_next=orders,
        unpriced=unpriced,
    )


def efficiency_spread(coupons: Sequence[Coupon]) -> Tuple[Optional[Coupon], Optional[Coupon], float]:
    """返回 (最高效的券, 最低效的券, 倍数)。

    这个倍数就是 README 首屏那个「同一分积分，价值差 12 倍」的来源。
    """
    ranked = rank(coupons)
    if len(ranked) < 2:
        return (ranked[0] if ranked else None), None, 0.0
    best, worst = ranked[0], ranked[-1]
    ratio = best.efficiency / worst.efficiency if worst.efficiency else 0.0
    return best, worst, round(ratio, 1)
