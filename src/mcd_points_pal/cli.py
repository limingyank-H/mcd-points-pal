"""命令行入口。

    python -m mcd_points_pal list                       # 券效率榜（默认离线）
    python -m mcd_points_pal advise --cart 9900005456:1 # 这单还能用积分换
    python -m mcd_points_pal checkout --cart 9900005456:1,P17078:1
    python -m mcd_points_pal report --out examples/points-report.html
    python -m mcd_points_pal demo                       # 一键盘跑上面全部
    python -m mcd_points_pal tools                      # 列出 MCP 提供的全部 Tool

加 `--live` 走真实 MCP（需要 MCD_MCP_TOKEN），不加则读 fixtures/。

安全边界：本工具**不会真正下单**。`checkout` 只做核价与账目推演，
真实下单必须由用户在麦当劳官方渠道完成。
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import List, Optional

from .datasource import FIXTURES, FixtureSource, McpSource
from .planner import build_plan, parse_cart
from .points import rank
from .render import advise_view, coupon_table, html_report, list_view


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mcd-points-pal",
        description="积分宝 · 把麦当劳积分券搬进点餐流程",
    )
    parser.add_argument("--live", action="store_true",
                        help="使用真实麦当劳 MCP（需要环境变量 MCD_MCP_TOKEN）")
    parser.add_argument("--store", default="1420888", help="门店编码，默认 1420888（深圳科技园长园得来速）")
    parser.add_argument("--be-type", type=int, default=1,
                        help="门店类型：1 到店 / 2 外送 / 5 得来速 / 6 团餐")
    parser.add_argument("--be-code", default=None, help="beType 为 2/5/6 时必传")
    parser.add_argument("--token", default=None, help="MCP Token，默认读 MCD_MCP_TOKEN")
    parser.add_argument("--fixtures", default=None, help="fixtures 目录")

    subs = parser.add_subparsers(dest="command")

    subs.add_parser("list", help="打印积分券效率榜")

    advise = subs.add_parser("advise", help="给定购物车，给出用积分建议")
    advise.add_argument("--cart", required=True, help="如 9900005456:1,P17078:1")
    advise.add_argument("--limit", type=int, default=3)

    checkout = subs.add_parser("checkout", help="核价与账目推演（不会真的下单）")
    checkout.add_argument("--cart", required=True)

    report = subs.add_parser("report", help="生成单文件 HTML 报告")
    report.add_argument("--cart", default="9900005456:1")
    report.add_argument("--out", default="examples/points-report.html")

    subs.add_parser("tools", help="列出 MCP 提供的全部 Tool")
    subs.add_parser("demo", help="离线跑通全部命令")
    return parser


def make_source(args):
    if args.live:
        return McpSource(
            token=args.token,
            store_code=args.store,
            be_type=args.be_type,
            be_code=args.be_code,
        )
    return FixtureSource(Path(args.fixtures) if args.fixtures else FIXTURES)


def cmd_list(source, args) -> int:
    active, stale = source.coupons()
    account = source.account()
    menu = source.menu()
    print(list_view(active, stale, account, menu, mode=source.mode))
    return 0


def cmd_advise(source, args) -> int:
    active, _stale = source.coupons()
    account = source.account()
    menu = source.menu()
    cart = parse_cart(args.cart)
    plan = build_plan(cart, active, menu, account, limit=args.limit)
    print(advise_view(plan, mode=source.mode))
    return 0


def cmd_checkout(source, args) -> int:
    active, _stale = source.coupons()
    account = source.account()
    menu = source.menu()
    cart = parse_cart(args.cart)
    plan = build_plan(cart, active, menu, account)
    summary = plan.summary

    print("")
    print("  结算推演（不会真的下单）")
    print("  " + "=" * 66)
    for line in summary.lines:
        tag = "[积分券]" if line.kind == "coupon" else "        "
        print("    %s %-26s ×%d   %s" % (tag, line.name, line.qty,
                                          "¥%.2f" % line.cash_total))
    print("")
    print("    商品原价      ¥%.2f" % summary.reference_total)
    if summary.points_used:
        print("    积分券省下     −¥%.2f  （用 %d 分）" % (summary.saved, summary.points_used))
    print("    " + "─" * 30)
    print("    实付          ¥%.2f" % summary.cash)
    print("")
    print("    积分 %.1f → 用掉 %d → 可得 %d → 结余 %.1f"
          % (account.available, summary.points_used, summary.earn_estimate, plan.balance_after))
    print("")
    print("  真实下单请在麦当劳官方小程序/App 完成。")
    print("")
    return 0


def cmd_report(source, args) -> int:
    active, stale = source.coupons()
    account = source.account()
    menu = source.menu()
    cart = parse_cart(args.cart)
    plan = build_plan(cart, active, menu, account)
    html = html_report(plan, rank(active), menu, stale_count=len(stale))
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html, encoding="utf-8")
    print("  ✅ 已生成 %s（%d bytes）" % (out, len(html.encode("utf-8"))))
    return 0


def cmd_tools(source, args) -> int:
    if not args.live:
        print("  `tools` 需要真实 MCP：请加 --live 并设置 MCD_MCP_TOKEN")
        return 1
    with McpSource(token=args.token, store_code=args.store,
                   be_type=args.be_type, be_code=args.be_code) as client:
        tools = client.client.list_tools()
        print("")
        print("  麦当劳 MCP 提供的 Tool 共 %d 个：" % len(tools))
        for tool in tools:
            desc = (tool.get("description") or "").splitlines()[0][:60]
            print("    %-32s %s" % (tool.get("name"), desc))
        print("")
    return 0


def cmd_demo(source, args) -> int:
    active, stale = source.coupons()
    account = source.account()
    menu = source.menu()
    print(list_view(active, stale, account, menu, mode=source.mode))

    cart = parse_cart("9900005456:1")
    plan = build_plan(cart, active, menu, account)
    print(advise_view(plan, mode=source.mode))

    out = Path("examples/points-report.html")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(html_report(plan, rank(active), menu, stale_count=len(stale)), encoding="utf-8")
    print("  ✅ 报告已生成：%s" % out)
    print("")
    return 0


COMMANDS = {
    "list": cmd_list,
    "advise": cmd_advise,
    "checkout": cmd_checkout,
    "report": cmd_report,
    "tools": cmd_tools,
    "demo": cmd_demo,
}


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.command:
        parser.print_help()
        return 0

    try:
        source = make_source(args)
        return COMMANDS[args.command](source, args)
    except (FileNotFoundError, ValueError, KeyError, RuntimeError) as exc:
        print("\n  ❌ %s\n" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
