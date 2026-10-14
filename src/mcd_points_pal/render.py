"""输出层：终端表格 + 单文件 HTML 报告。

单文件 HTML 是刻意设计的——它同时承担两个角色：
  1. 用户可以直接双击打开、截图分享
  2. 是「产物示例」（examples/ 里那份就是这么生成的）
"""

from __future__ import annotations

import html as html_mod
import unicodedata
from datetime import datetime
from typing import Iterable, List, Optional, Sequence

from .models import Account, Coupon, Menu
from .planner import Plan, efficiency_spread
from .points import money, money4, rank


# ---------- 宽度感知的终端对齐（中文占两格） ----------

def display_width(text: str) -> int:
    total = 0
    for char in str(text):
        total += 2 if unicodedata.east_asian_width(char) in ("W", "F") else 1
    return total


def pad(text: str, width: int, align: str = "l") -> str:
    text = str(text)
    gap = max(width - display_width(text), 0)
    if align == "r":
        return " " * gap + text
    if align == "c":
        left = gap // 2
        return " " * left + text + " " * (gap - left)
    return text + " " * gap


def truncate(text: str, width: int) -> str:
    text = str(text)
    if display_width(text) <= width:
        return text
    out = ""
    for char in text:
        if display_width(out + char) > width - 1:
            break
        out += char
    return out + "…"


# ---------- 终端 ----------

HEADERS = ("#", "券", "积分", "券价", "对照价", "省", "每积分")
WIDTHS = (3, 26, 6, 9, 9, 9, 10)


def coupon_table(coupons: Sequence[Coupon], balance: Optional[float] = None) -> str:
    """按每积分效率降序打印券榜。

    排序在这里做，而不是交给调用方 —— 券榜的唯一正确顺序就是效率序，
    放在渲染层可以保证任何入口都不会打出未排序的表。
    """
    coupons = list(rank(coupons))
    rows: List[str] = []
    rows.append("  " + pad(HEADERS[0], WIDTHS[0])
                + pad(HEADERS[1], WIDTHS[1])
                + "".join(pad(h, w, "r") for h, w in zip(HEADERS[2:], WIDTHS[2:])))
    rows.append("  " + "-" * (sum(WIDTHS) + 4))

    for index, coupon in enumerate(coupons, 1):
        tag = ""
        if index == 1:
            tag = "  ← 最值"
        elif index == len(coupons):
            tag = "  ← 最不值"
        if balance is not None and coupon.points > balance:
            tag = "  ← 积分还差 %d" % (coupon.points - balance)
        rows.append(
            "  "
            + pad(str(index), WIDTHS[0])
            + pad(truncate(coupon.name, WIDTHS[1]), WIDTHS[1])
            + pad(str(coupon.points), WIDTHS[2], "r")
            + pad(money(coupon.price), WIDTHS[3], "r")
            + pad(money(coupon.reference_total or 0), WIDTHS[4], "r")
            + pad(money(coupon.save), WIDTHS[5], "r")
            + pad(money4(coupon.efficiency), WIDTHS[6], "r")
            + tag
        )
    return "\n".join(rows)


def list_view(coupons: Sequence[Coupon], stale: Sequence[Coupon], account: Account,
              menu: Optional[Menu] = None, mode: str = "fixture") -> str:
    best, worst, ratio = efficiency_spread(coupons)
    lines: List[str] = []
    lines.append("")
    lines.append("  积分宝 · 积分券效率榜")
    lines.append("  " + "=" * 66)
    lines.append("  数据源：%s%s" % ("离线 fixtures" if mode == "fixture" else "麦当劳 MCP（实时）",
                                  "" if menu is None else "　门店：%s" % menu.store_name))
    lines.append("  账户：可用 %.1f 分　本月将过期 %.0f 分　累计已过期 %.1f 分"
                 % (account.available, account.expiring_this_month, account.expired))
    lines.append("")
    lines.append(coupon_table(coupons, account.available))
    lines.append("")
    if best and worst:
        lines.append("  省同样的钱，积分可以差 %.1f 倍：" % ratio)
        lines.append("      %s：%d 分省 %s（每积分 %s）"
                     % (best.name, best.points, money(best.save), money4(best.efficiency)))
        lines.append("      %s：%d 分省 %s（每积分 %s）"
                     % (worst.name, worst.points, money(worst.save), money4(worst.efficiency)))
        lines.append("")
    if stale:
        lines.append("  已剔除 %d 张「假上架」券（downTime 已过，但接口 status 仍是 2 上架）："
                     % len(stale))
        for coupon in sorted(stale, key=lambda c: c.down_time)[:3]:
            lines.append("      %s（%s 已下架）" % (truncate(coupon.name, 24), coupon.down_time))
        if len(stale) > 3:
            lines.append("      …… 其余 %d 张" % (len(stale) - 3))
        lines.append("")
    return "\n".join(lines)


def advise_view(plan: Plan, mode: str = "fixture") -> str:
    summary = plan.summary
    account = plan.account
    lines: List[str] = []
    lines.append("")
    lines.append("  积分宝 · 这单还能用积分换" + ("（离线 fixtures）" if mode == "fixture" else "（麦当劳 MCP 实时）"))
    lines.append("  " + "=" * 66)
    lines.append("")
    lines.append("  本单：%d 件" % summary.item_count)
    for line in summary.lines:
        marker = "[积分券]" if line.kind == "coupon" else "        "
        extra = "　(%d 分)" % line.points_total if line.kind == "coupon" else ""
        lines.append("    %s %s ×%d　%s%s"
                     % (marker, truncate(line.name, 22), line.qty, money(line.cash_total), extra))
    lines.append("")
    lines.append("    正常点单            %s" % money(summary.reference_total))
    if summary.points_used:
        lines.append("    积分券省下（用 %d 分）  −%s" % (summary.points_used, money(summary.saved)))
    lines.append("    预计本单可得        +%d 分　（¥1 = 1 分，示意口径）" % summary.earn_estimate)
    lines.append("    " + "─" * 52)
    lines.append("    实付                %s" % money(summary.cash))
    lines.append("")
    if plan.recommended:
        lines.append("  还能顺手换（余额 %.1f 分，其中 %.0f 分本月过期）："
                     % (account.available, account.expiring_this_month))
        for coupon in plan.recommended:
            lines.append("      %s　%d 分 + %s　省 %s　每积分 %s"
                         % (pad(truncate(coupon.name, 22), 22), coupon.points,
                            money(coupon.price), money(coupon.save), money4(coupon.efficiency)))
    else:
        lines.append("  当前余额换不起更多有效券 —— 先攒分。")
    lines.append("")
    lines.append("  积分：%.1f → 用掉 %d → 可得 %d → 结余 %.1f"
                 % (account.available, summary.points_used, summary.earn_estimate,
                    plan.balance_after))
    if plan.next_coupon is not None and plan.orders_until_next:
        lines.append("  下一次目标：再攒 %.1f 分可换「%s」（%d 分）"
                     % (plan.next_coupon.points - plan.balance_after,
                        plan.next_coupon.name, plan.next_coupon.points))
        lines.append("              按今天这单的速度，约再来 %d 次。"
                     % plan.orders_until_next)
    lines.append("")
    lines.append("  提醒：积分券是「随单核销」的——必须和这顿饭一起下单才生效，出了页面就用不上了。")
    lines.append("")
    return "\n".join(lines)


# ---------- 单文件 HTML 报告 ----------

def html_report(plan: Plan, coupons: Sequence[Coupon], menu: Optional[Menu] = None,
                stale_count: int = 0, generated_at: Optional[datetime] = None) -> str:
    generated_at = generated_at or datetime.now()
    esc = html_mod.escape
    best, worst, ratio = efficiency_spread(coupons)
    summary = plan.summary

    rows = []
    for index, coupon in enumerate(coupons, 1):
        flag = "best" if index == 1 else ("worst" if index == len(coupons) else "")
        rows.append(
            '<tr class="%s"><td class="rk">%d</td><td class="nm">%s</td>'
            '<td class="num">%d</td><td class="num">%s</td><td class="num">%s</td>'
            '<td class="num save">%s</td><td class="num eff">%s</td></tr>'
            % (flag, index, esc(coupon.name), coupon.points, money(coupon.price),
               money(coupon.reference_total or 0), money(coupon.save), money4(coupon.efficiency))
        )

    cart_rows = "".join(
        '<li><span>%s%s ×%d</span><b>%s</b></li>'
        % ("[积分券] " if line.kind == "coupon" else "", esc(line.name), line.qty,
           money(line.cash_total))
        for line in summary.lines
    )

    recs = "".join(
        '<div class="rec"><span class="rn">%s</span>'
        '<span class="rp">%d 分 + %s</span>'
        '<span class="rs">省 %s</span></div>'
        % (esc(c.name), c.points, money(c.price), money(c.save))
        for c in plan.recommended
    ) or '<p class="muted">当前余额换不起更多有效券。</p>'

    goal = ""
    if plan.next_coupon is not None and plan.orders_until_next:
        goal = ('<p>下一次目标：再攒 <b>%.1f 分</b> 可换「%s」（%d 分），'
                '按今天这单的速度约再来 <b>%d 次</b>。</p>'
                % (plan.next_coupon.points - plan.balance_after,
                   esc(plan.next_coupon.name), plan.next_coupon.points, plan.orders_until_next))

    template = """<!DOCTYPE html>
<html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>积分宝 · 积分券效率报告</title>
<style>
:root{--red:#DA291C;--yel:#FFC72C;--ink:#1A1A18;--gray:#6B675F;--line:#E8E4DC;--bg:#F7F5F1}
*{box-sizing:border-box}
body{margin:0;background:var(--bg);color:var(--ink);
 font:14px/1.65 -apple-system,"PingFang SC","Microsoft YaHei",system-ui,sans-serif}
.wrap{max-width:900px;margin:0 auto;padding:44px 24px 64px}
h1{font-size:26px;font-weight:500;margin:0 0 6px}
.sub{color:var(--gray);margin:0 0 32px}
.card{background:#fff;border:1px solid var(--line);border-radius:14px;padding:22px 24px;margin-bottom:18px}
h2{font-size:15px;font-weight:500;margin:0 0 14px}
.hero{display:flex;gap:28px;align-items:baseline;flex-wrap:wrap}
.hero b{font-size:34px;font-weight:500;color:var(--red)}
.hero span{color:var(--gray)}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums}
th{font-weight:500;color:var(--gray);text-align:right;padding:8px 10px;border-bottom:1px solid var(--line)}
th:nth-child(2){text-align:left}
td{padding:9px 10px;border-bottom:1px solid #F2EFE9}
td.nm{font-weight:400}
.num{text-align:right}
.rk{color:var(--gray)}
tr.best{background:#FFFBF0}tr.best .eff{color:var(--red);font-weight:500}
tr.worst{color:#9A958C}
.save{color:#1D9E75}
ul{list-style:none;margin:0;padding:0}
ul li{display:flex;justify-content:space-between;padding:7px 0;border-bottom:1px solid #F2EFE9}
.total{display:flex;justify-content:space-between;padding:12px 0 0;font-size:16px}
.total b{font-size:22px;font-weight:500;color:var(--red)}
.rec{display:flex;gap:14px;align-items:baseline;padding:8px 0;border-bottom:1px solid #F2EFE9}
.rec .rn{flex:1}
.rec .rp{color:var(--gray)}
.rec .rs{color:#1D9E75;min-width:82px;text-align:right}
.note{color:var(--gray);font-size:13px;margin:14px 0 0}
.foot{color:#9A958C;font-size:12px;margin-top:26px;line-height:1.8}
@media(max-width:620px){.hide-s{display:none}}
</style></head><body><div class="wrap">
<h1>积分宝 · 积分券效率报告</h1>
<p class="sub">数据来源：麦当劳 MCP（门店菜单 / 积分券 / 积分账户）　·　生成时间 {{ts}}</p>

<div class="card">
  <h2>一句话结论</h2>
  <div class="hero">
    <b>{{ratio}} 倍</b>
    <span>同样是花积分，效率最高的券每分省 {{best_eff}}，最低的只省 {{worst_eff}}。</span>
  </div>
  <p class="note">{{best_name}}（{{best_pt}} 分省 {{best_save}}）　vs　{{worst_name}}（{{worst_pt}} 分省 {{worst_save}}）</p>
</div>

<div class="card">
  <h2>积分券效率榜（{{active}} 张有效 / 已剔除 {{stale}} 张假上架）</h2>
  <table><thead><tr><th>#</th><th>券</th><th>积分</th><th>券价</th><th>对照价</th><th>省</th><th>每积分</th></tr></thead>
  <tbody>{{rows}}</tbody></table>
</div>

<div class="card">
  <h2>本单</h2>
  <ul>{{cart_rows}}</ul>
  <div class="total"><span>正常点单 {{reference}}　·　积分券省 {{saved}}（用 {{points}} 分）　·　预计可得 +{{earn}} 分</span>
  <b>实付 {{cash}}</b></div>
</div>

<div class="card">
  <h2>还能顺手换（余额 {{balance}} 分，其中 {{expiring}} 分本月过期）</h2>
  {{recs}}
  {{goal}}
  <p class="note">积分券是「随单核销」的——必须和这顿饭一起下单才生效。</p>
</div>

<p class="foot">
  对照价口径：每张券都对应一份「用现金买要花多少钱」的参照餐品，取门店菜单的单点价；
  省 = 对照价 − 券价。完整核价表见 fixtures/coupon_reference.json，可逐条审计。<br>
  本报告由 `python -m mcd_points_pal report` 生成，全部数字来自麦当劳 MCP 返回值，未做任何估算。
</p>
</div></body></html>"""
    values = {
        "ts": generated_at.strftime("%Y-%m-%d %H:%M"),
        "best_eff": money4(best.efficiency) if best else "—",
        "worst_eff": money4(worst.efficiency) if worst else "—",
        "best_name": esc(best.name) if best else "—",
        "best_save": money(best.save) if best else "—",
        "worst_name": esc(worst.name) if worst else "—",
        "worst_save": money(worst.save) if worst else "—",
        "rows": "".join(rows),
        "cart_rows": cart_rows,
        "reference": money(summary.reference_total),
        "saved": money(summary.saved),
        "cash": money(summary.cash),
        "recs": recs,
        "goal": goal,
        "balance": "%.1f" % plan.account.available,
        "expiring": "%.0f" % plan.account.expiring_this_month,
        "ratio": ("%.1f" % ratio) if ratio else "—",
        "best_pt": str(best.points) if best else "—",
        "worst_pt": str(worst.points) if worst else "—",
        "points": str(summary.points_used),
        "earn": str(summary.earn_estimate),
        "active": str(len(coupons)),
        "stale": str(stale_count),
    }
    for key, value in values.items():
        template = template.replace("{{%s}}" % key, str(value))
    return template
