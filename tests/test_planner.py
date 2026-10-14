"""推荐引擎与购物车账目的测试。"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_points_pal.models import Account, Coupon, Menu, MenuProduct  # noqa: E402
from mcd_points_pal.planner import (  # noqa: E402
    build_plan,
    build_summary,
    coupon_id_of,
    efficiency_spread,
    parse_cart,
)


def menu() -> Menu:
    return Menu(
        store_code="1420888",
        store_name="测试店",
        products={
            "9900005456": MenuProduct("9900005456", "麦辣鸡腿汉堡三件套", 33.5, 47.0),
            "1100": MenuProduct("1100", "巨无霸", 26.5, 26.5),
            "515837": MenuProduct("515837", "圆筒冰淇淋", 5.0, 5.0),
        },
    )


def coupons() -> list:
    return [
        Coupon(17073, "6.9元可乐麦炫酷", 50, 6.9, reference_total=13.5, reference_source="menu"),
        Coupon(17078, "16.9元2份麦辣鸡翅", 200, 16.9, reference_total=29.0, reference_source="menu"),
        Coupon(17081, "21.9元巨无霸可乐组合", 800, 21.9, reference_total=36.0, reference_source="menu"),
        Coupon(99999, "过期但被标上架", 50, 6.9, reference_total=13.5,
               reference_source="menu", down_time="2026-03-21 23:59:59"),
    ]


def account(available=536.8) -> Account:
    return Account(available=available, expiring_this_month=91, expired=915.6)


# ---------- parse_cart ----------

def test_parse_cart_basic_and_coupons():
    assert parse_cart("9900005456:2,P17078:1") == {"9900005456": 2, "P17078": 1}
    assert parse_cart("1100") == {"1100": 1}
    assert parse_cart("") == {}
    assert parse_cart(" 1100 : 3 , P17078 ") == {"1100": 3, "P17078": 1}


def test_parse_cart_rejects_bad_quantity():
    with pytest.raises(ValueError):
        parse_cart("1100:x")
    with pytest.raises(ValueError):
        parse_cart("1100:0")


def test_coupon_id_of():
    assert coupon_id_of("P17078") == 17078
    assert coupon_id_of("1100") is None
    assert coupon_id_of("Pabc") is None


# ---------- 账目 ----------

def test_summary_separates_cash_from_reference():
    """省 = 对照价 − 券价，这两个数不能混。"""
    summary = build_summary({"9900005456": 1, "P17078": 1}, coupons(), menu())
    assert summary.cash == 50.40          # 33.5 + 16.9（券价）
    assert summary.reference_total == 62.50  # 33.5 + 29.0（单点价）
    assert summary.saved == 12.10
    assert summary.points_used == 200
    assert summary.item_count == 2


def test_summary_ignores_nonexistent_coupon():
    with pytest.raises(KeyError):
        build_summary({"P000": 1}, coupons(), menu())


def test_summary_ignores_off_menu_product():
    """calculate-price 对失效编码静默丢弃——这里必须显式报错而不是悄悄算错。"""
    with pytest.raises(KeyError):
        build_summary({"3050": 1}, coupons(), menu())  # 旧可乐中杯，已换编码


# ---------- 计划 ----------

def test_plan_recommends_affordable_and_unpicked():
    """真实链路里 build_plan 拿到的已经是 split_by_validity 过滤后的有效券。"""
    from mcd_points_pal.points import split_by_validity

    active, stale = split_by_validity(coupons())
    assert [c.spu_id for c in stale] == [99999]

    plan = build_plan({"9900005456": 1}, active, menu(), account())
    ids = [c.spu_id for c in plan.recommended]
    assert 17078 in ids and 17073 in ids
    assert 99999 not in ids          # 假上架券已被上游过滤
    assert plan.summary.cash == 33.50
    assert plan.balance_after == 569.8


def test_plan_next_goal_and_pace():
    plan = build_plan({"9900005456": 1, "P17078": 1}, coupons(), menu(), account())
    # 536.8 - 200 + 50 = 386.8，下一档 800 分，差 413.2，每单 +50 → 9 次
    assert plan.balance_after == 386.8
    assert plan.next_coupon is not None and plan.next_coupon.spu_id == 17081
    assert plan.orders_until_next == 9


def test_plan_excludes_already_picked_coupon_from_recommendations():
    plan = build_plan({"P17078": 1}, coupons(), menu(), account())
    assert 17078 not in [c.spu_id for c in plan.recommended]


# ---------- 12 倍 ----------

def test_efficiency_spread_matches_headline_claim():
    real = [c for c in coupons() if c.spu_id != 99999]
    extra = Coupon(17075, "3.9元圆筒冰淇淋", 100, 3.9,
                   reference_total=5.0, reference_source="menu")
    best, worst, ratio = efficiency_spread(real + [extra])
    assert best.spu_id == 17073
    assert worst.spu_id == 17075
    assert ratio == 12.0
