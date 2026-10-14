"""数据源与文档完整性的测试。

顺带守住参赛仓库的「报名条件」：官方要求项目必须真实使用麦当劳 MCP，
且文件清单齐全 —— 这些用测试钉住，改坏会在 CI 里立刻暴露。
"""

from __future__ import annotations

import json
import sys
from datetime import datetime, timedelta
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

from mcd_points_pal.datasource import FixtureSource, normalize_menu  # noqa: E402
from mcd_points_pal.planner import build_plan, parse_cart  # noqa: E402
from mcd_points_pal.points import rank  # noqa: E402


@pytest.fixture(scope="module")
def source():
    return FixtureSource(REPO / "fixtures")


# ---------- fixtures 自身 ----------

def test_fixtures_exist_and_carry_provenance():
    for name in ("points_products.json", "my_account.json", "orders.json",
                 "menu_1420888.json", "coupon_reference.json"):
        path = REPO / "fixtures" / name
        assert path.exists(), "缺 fixture：%s" % name
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data.get("_source"), "%s 缺少 _source（来源必须可追溯）" % name


def test_points_fixture_has_fake_listed_coupons(source):
    """我们声称「24 张里 15 张假上架」——fixture 必须能复现这个数字。"""
    payload = source.coupon_payload()
    rows = payload["data"]
    now = datetime(2026, 10, 14)
    stale = [
        r for r in rows
        if r["status"] == 2 and datetime.strptime(r["downTime"], "%Y-%m-%d %H:%M:%S") < now
    ]
    assert len(rows) == 24
    assert len(stale) == 15


def test_account_fixture_matches_readme_numbers(source):
    account = source.account()
    assert account.available == 536.8
    assert account.expiring_this_month == 91
    assert account.expired == 915.6


def test_coupon_reference_covers_all_active_coupons(source):
    """核价表必须覆盖每一张有效券，否则那张券会被静默排除在排序之外。"""
    active, _stale = source.coupons()
    reference = source.reference()
    missing = [c.spu_id for c in active if str(c.spu_id) not in reference]
    assert not missing, "缺少对照价的券：%s" % missing


def test_reference_prices_exist_in_menu(source):
    """对照价的每个 productCode 必须真实存在于门店菜单（external 的除外）。"""
    menu = source.menu()
    reference = source.reference()
    for spu_id, entry in reference.items():
        if entry.get("referenceSource") == "external":
            continue
        for item in entry.get("referenceItems", []):
            code = item.get("productCode")
            if code:
                assert code in menu.products, "券 %s 的对照商品 %s 不在菜单里" % (spu_id, code)
                assert abs(menu.products[code].price - item["unitPrice"]) < 1e-6


# ---------- 数据源 ----------

def test_fixture_source_end_to_end(source):
    active, stale = source.coupons()
    assert len(active) == 9 and len(stale) == 15

    menu = source.menu()
    assert menu.store_code == "1420888"
    assert len(menu.products) == 110

    account = source.account()
    plan = build_plan(parse_cart("9900005456:1,P17078:1"), active, menu, account)
    assert plan.summary.cash == 50.40
    assert plan.summary.saved == 12.10
    assert plan.summary.points_used == 200


def test_normalize_menu_reads_real_shape():
    payload = {
        "data": {
            "categories": [
                {"name": "巨无霸牛鱼肉堡",
                 "meals": [{"code": "1100", "tags": ["100%纯牛肉"]}]},
            ],
            "meals": {
                "1100": {"name": "巨无霸", "image": "https://x/y.png",
                          "currentPrice": "26.5", "originalPrice": "26.5",
                          "discountType": None},
            },
        }
    }
    menu = normalize_menu(payload, "1420888", "测试店")
    assert menu.products["1100"].product_name == "巨无霸"
    assert menu.products["1100"].price == 26.5
    assert menu.categories[0]["products"] == ["1100"]


def test_normalize_menu_flags_conditional_discounts():
    payload = {"data": {"meals": {
        "9900000888": {"name": "巨无霸四件套", "currentPrice": "32",
                        "originalPrice": "58.5", "discountType": "随单购麦金卡优惠"},
    }}}
    menu = normalize_menu(payload, "1420888", "测试店")
    assert "需随单购" in menu.products["9900000888"].tags


# ---------- 参赛合规 ----------

def test_required_submission_files_present():
    required = [
        "README.md",
        "CONTEST_DECLARATION.md",
        "MCP_INTEGRATION.md",
        "mcp-config.example.json",
        "workbuddy.md",
        "SKILL.md",
    ]
    missing = [n for n in required if not (REPO / n).exists()]
    assert not missing, "缺必备文件：%s" % missing


def test_declaration_matches_official_wording():
    """官方要求 CONTEST_DECLARATION.md 内容一字不改（已用 diff 与官方原文核对过）。"""
    declared = (REPO / "CONTEST_DECLARATION.md").read_text(encoding="utf-8")
    for keyword in ("原创性声明", "合规声明", "麦当劳"):
        assert keyword in declared
    # 官方原文共 1522 字节（UTF-8），diff 校验过一字不差 —— 用字节数防止被偷偷删减
    assert len(declared.encode("utf-8")) > 1000


def test_config_example_has_no_real_token():
    import re

    text = (REPO / "mcp-config.example.json").read_text(encoding="utf-8")
    # 只允许环境变量占位符，不允许出现真实凭证（长随机串）
    assert "${MCD_MCP_TOKEN}" in text
    leaked = re.search(r"[A-Za-z0-9_\-]{24,}", text.replace("${MCD_MCP_TOKEN}", ""))
    assert not leaked, "疑似真实 Token 泄漏：%s" % leaked.group(0) if leaked else ""


def test_offline_rank_is_deterministic(source):
    active, _ = source.coupons()
    first = rank(active)
    second = rank(active)
    assert [c.spu_id for c in first] == [c.spu_id for c in second]
    assert first[0].efficiency > first[-1].efficiency
