#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
积分宝 · 积分效率计算器（免 Token 可跑）

麦当劳的积分不能单独兑换，它换到的是一张「到店专用」的特价购买券，
必须和这顿饭一起下单才生效。所以「划不划算」是可以精确算出来的。

本脚本用一份实测数据快照，让你不配置 MCP 也能先跑通核心逻辑。

数据来源：MCP mcd-mcp
  - mall-points-products(catRuleIds="1>4")  积分券列表（已按 downTime 剔除「假上架」）
  - mall-product-detail(skuId)              券详情
  - query-meals(storeCode, orderType, beType)  门店菜单单点价（用于算「省多少」）
  - query-my-account()                      积分账户

用法：
  python3 points_value.py list
  python3 points_value.py advise --cart 9900005456:1
  python3 points_value.py order  --cart 9900005456:1 --coupon 17078
  python3 points_value.py advise --cart 9900005456:1 --balance 120
"""

import argparse
import unicodedata

# ---------------------------------------------------------------- 数据快照

# 积分券：仅保留 downTime 未过期的 9 张
# 接口实际返回 24 张，其中 15 张 downTime 已过但 status 仍为 2（上架）——需自行过滤
COUPONS = [
    {"id": 17073, "name": "6.9元可乐麦炫酷",       "points": 50,  "price": 6.9,  "ref": 13.5,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17074, "name": "6.9元香芋派/菠萝派任选", "points": 50,  "price": 6.9,  "ref": 8.5,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17076, "name": "10.9元指定小食任选",    "points": 100, "price": 10.9, "ref": 14.5,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17075, "name": "3.9元圆筒冰淇淋",       "points": 100, "price": 3.9,  "ref": 5.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17078, "name": "16.9元2份麦辣鸡翅",     "points": 200, "price": 16.9, "ref": 29.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17077, "name": "10.9元指定小食任选",    "points": 200, "price": 10.9, "ref": 14.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17079, "name": "16.9元麦辣可乐组合",    "points": 500, "price": 16.9, "ref": 32.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17080, "name": "17.9元板烧可乐组合",    "points": 500, "price": 17.9, "ref": 33.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
    {"id": 17081, "name": "21.9元巨无霸可乐组合",  "points": 800, "price": 21.9, "ref": 36.0,
     "down": "2026-12-30 23:59:59", "cat": "到店专用"},
]

# 门店菜单子集（深圳科技园长园得来速 1420888 实测价），用于演示购物车
MENU = {
    "9900005456": ("麦辣鸡腿汉堡三件套", 33.5),
    "1100":       ("巨无霸",            26.5),
    "1700":       ("麦辣鸡翅",          14.5),
    "4810":       ("薯条",              14.5),
    "9900008751": ("可乐",               9.5),
    "515837":     ("圆筒冰淇淋",         5.0),
}

DEFAULT_BALANCE = 536.8   # 示例账户余额（MCP query-my-account 实测值）
EXPIRING = 91.0           # 本月将过期积分（示例）
EARN_RATE = 1             # 消费积分规则：¥1 = 1 分（演示口径）


# ---------------------------------------------------------------- 排版工具

def dwidth(s: str) -> int:
    """中英文混排的显示宽度（汉字/全角占 2 列）"""
    return sum(2 if unicodedata.east_asian_width(c) in "WF" else 1 for c in s)


def pad(s: str, width: int, align: str = "l") -> str:
    gap = width - dwidth(s)
    if gap <= 0:
        return s
    return s + " " * gap if align == "l" else " " * gap + s


def money(v: float) -> str:
    return "¥%.2f" % v


def rate_fmt(v: float) -> str:
    """每积分效率——保留 4 位小数，否则 12 倍的差距会被四舍五入抹平"""
    return "¥%.4f" % v


def efficiency(c: dict) -> float:
    """每积分省多少钱——本项目的核心指标"""
    return (c["ref"] - c["price"]) / c["points"]


def save_of(c: dict) -> float:
    return c["ref"] - c["price"]


def sorted_coupons():
    return sorted(COUPONS, key=efficiency, reverse=True)


# ---------------------------------------------------------------- 命令实现

def cmd_list(_args):
    print()
    print("积分效率榜 · 每积分省多少钱")
    print("数据来源：MCP mall-points-products(1>4) + mall-product-detail + query-meals")
    print("已按 downTime 剔除未生效券（实测 24 张里有 15 张是「假上架」）")
    print()
    print("  " + pad("#", 3) + pad("券", 26) + pad("积分", 7, "r") + pad("券价", 9, "r")
          + pad("单点价", 10, "r") + pad("省", 9, "r") + pad("每积分", 12, "r"))
    print("  " + "-" * 78)
    rank = sorted_coupons()
    for i, c in enumerate(rank, 1):
        tag = ""
        if i == 1:
            tag = "  ← 最值"
        elif i == len(rank):
            tag = "  ← 最不值"
        print("  " + pad(str(i), 3) + pad(c["name"], 26) + pad(str(c["points"]), 7, "r")
              + pad(money(c["price"]), 9, "r") + pad(money(c["ref"]), 10, "r")
              + pad(money(save_of(c)), 9, "r") + pad(rate_fmt(efficiency(c)), 12, "r") + tag)
    print()
    ratio = efficiency(rank[0]) / efficiency(rank[-1])
    print("  效率最高 / 最低 = %.1f 倍" % ratio)
    print()
    print("  两个自己很难发现的事实：")
    print("   1. 省下差不多的钱，积分差 4 倍：省 %s 用 %d 分，省 %s 用 %d 分"
          % (money(save_of(rank[1])), rank[1]["points"],
             money(save_of([c for c in rank if c["points"] == 800][0])),
             [c for c in rank if c["points"] == 800][0]["points"]))
    same = [c for c in COUPONS if c["name"] == "10.9元指定小食任选"]
    if len(same) == 2:
        a, b = sorted(same, key=lambda x: x["points"])
        print("   2. 同名不同价：都叫「10.9元指定小食任选」，%d 分那张省 %s，%d 分那张只省 %s"
              % (a["points"], money(save_of(a)), b["points"], money(save_of(b))))
    print()


def parse_cart(spec: str):
    """'9900005456:1,1100:2' -> [{'code','name','price','qty'}]"""
    items = []
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        code, _, qty = part.partition(":")
        qty = int(qty) if qty else 1
        name, price = MENU.get(code, ("未知商品(%s)" % code, 0.0))
        items.append({"code": code, "name": name, "price": price, "qty": qty})
    return items


def compute(items, coupon, balance):
    normal = sum(i["price"] * i["qty"] for i in items)
    cash = normal
    points_used = 0
    if coupon:
        normal += coupon["ref"]
        cash += coupon["price"]
        points_used = coupon["points"]
    earn = int(cash * EARN_RATE)
    after = balance - points_used + earn
    return {
        "normal": normal, "cash": cash, "save": normal - cash,
        "points_used": points_used, "earn": earn,
        "balance": balance, "after": after,
    }


def cmd_advise(args):
    items = parse_cart(args.cart)
    balance = args.balance
    if not items:
        print("购物车为空。示例：python3 points_value.py advise --cart 9900005456:1")
        return

    print()
    print("购物车")
    for i in items:
        print("  " + pad("%s ×%d" % (i["name"], i["qty"]), 46)
              + pad(money(i["price"] * i["qty"]), 10, "r"))
    subtotal = sum(i["price"] * i["qty"] for i in items)
    print("  " + pad("", 46) + pad("-" * 10, 10, "r"))
    print("  " + pad("小计", 46) + pad(money(subtotal), 10, "r"))
    print()

    pool = [c for c in sorted_coupons() if c["points"] <= balance]
    if not pool:
        print("  当前 %.1f 分还不够兑换任何券。建议先下单攒分。" % balance)
        print()
        return

    top = pool[0]
    print("推荐用积分换（余额 %.1f 分%s）" % (balance, "，其中 %.0f 分本月过期" % EXPIRING))
    print("  ★ " + pad(top["name"], 24)
          + pad("%d 分 + %s" % (top["points"], money(top["price"])), 19)
          + pad("省 " + money(save_of(top)), 13)
          + "每积分 " + rate_fmt(efficiency(top)))
    if len(pool) > 1:
        print("  其他可选：")
        for c in pool[1:4]:
            print("    · " + pad(c["name"], 24)
                  + pad("%d 分 + %s" % (c["points"], money(c["price"])), 19)
                  + pad("省 " + money(save_of(c)), 13)
                  + "每积分 " + rate_fmt(efficiency(c)))
    print()

    r = compute(items, top, balance)
    print("结算（若换上「%s」）" % top["name"])
    print("  " + pad("正常点单", 40) + pad(money(r["normal"]), 12, "r"))
    print("  " + pad("积分券省下（用 %d 分）" % r["points_used"], 40)
          + pad("−" + money(r["save"]), 12, "r"))
    print("  " + pad("实付", 40) + pad(money(r["cash"]), 12, "r"))
    print()
    print("  本单可得积分：+%d 分" % r["earn"])
    print("  积分余额：%.1f → %.1f → %.1f" % (balance, balance - r["points_used"], r["after"]))
    nxt = [c for c in sorted_coupons() if c["points"] > r["after"]]
    if nxt:
        t = min(nxt, key=lambda c: c["points"])
        print("  下次目标：再攒 %.1f 分可换「%s」" % (t["points"] - r["after"], t["name"]))
    print()


def cmd_order(args):
    items = parse_cart(args.cart)
    balance = args.balance
    coupon = None
    if args.coupon:
        coupon = next((c for c in COUPONS if c["id"] == int(args.coupon)), None)
        if coupon is None:
            print("找不到券 %s（可先运行 list 查看可用券 ID）" % args.coupon)
            return
    if coupon and coupon["points"] > balance:
        print("积分不足：该券需要 %d 分，当前 %.1f 分。" % (coupon["points"], balance))
        return

    r = compute(items, coupon, balance)
    print()
    print("下单成功 · 到店取餐码 A128")
    print()
    for i in items:
        print("  " + pad("%s ×%d" % (i["name"], i["qty"]), 46)
              + pad(money(i["price"] * i["qty"]), 10, "r"))
    if coupon:
        print("  " + pad("%s ×1" % coupon["name"], 40) + pad("[用 %d 分]" % coupon["points"], 12)
              + pad(money(coupon["price"]), 10, "r"))
    print("  " + pad("", 46) + pad("-" * 10, 10, "r"))
    print("  " + pad("实付", 46) + pad(money(r["cash"]), 10, "r"))
    print()
    print("  积分已到账  +%d 分" % r["earn"])
    print("  积分余额    %.1f 分" % r["after"])
    nxt = [c for c in sorted_coupons() if c["points"] > r["after"]]
    if nxt:
        t = min(nxt, key=lambda c: c["points"])
        gap = t["points"] - r["after"]
        times = max(1, -(-int(gap) // max(r["earn"], 1)))
        print("  下次目标    再攒 %.1f 分，就能换「%s」" % (gap, t["name"]))
        print("              按今天这单的速度，约再来 %d 次" % times)
    print()


# ---------------------------------------------------------------- 入口

def main():
    p = argparse.ArgumentParser(
        description="积分宝 · 积分效率计算器（麦当劳 MCP 实测数据快照，免 Token 可跑）",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例：
  python3 points_value.py list
  python3 points_value.py advise --cart 9900005456:1
  python3 points_value.py advise --cart 9900005456:1 --balance 120
  python3 points_value.py order  --cart 9900005456:1 --coupon 17078
""")
    sub = p.add_subparsers(dest="cmd")

    s1 = sub.add_parser("list", help="查看积分效率榜")
    s1.set_defaults(func=cmd_list)

    s2 = sub.add_parser("advise", help="给购物车推荐最优积分券")
    s2.add_argument("--cart", required=True, help="购物车，格式 商品编码:数量,商品编码:数量")
    s2.add_argument("--balance", type=float, default=DEFAULT_BALANCE, help="可用积分")
    s2.set_defaults(func=cmd_advise)

    s3 = sub.add_parser("order", help="模拟下单并查看积分到账")
    s3.add_argument("--cart", required=True, help="购物车，格式 商品编码:数量")
    s3.add_argument("--coupon", help="使用的券 spuId（如 17078）")
    s3.add_argument("--balance", type=float, default=DEFAULT_BALANCE, help="可用积分")
    s3.set_defaults(func=cmd_order)

    args = p.parse_args()
    if not getattr(args, "func", None):
        p.print_help()
        print()
        print("提示：先试试  python3 points_value.py list")
        return
    args.func(args)


if __name__ == "__main__":
    main()
