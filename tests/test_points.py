"""券清洗与排序的测试 —— 本项目方法学的核心，必须可验证。"""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from mcd_points_pal.models import Coupon  # noqa: E402
from mcd_points_pal.points import (  # noqa: E402
    affordable,
    next_goal,
    parse_coupons,
    parse_time,
    rank,
    split_by_validity,
)

NOW = datetime(2026, 10, 14, 12, 0, 0)


def coupon(spu_id=1, name="测试券", points=100, price=10.0, status=2,
           down_time="2026-12-30 23:59:59", ref=15.0):
    return Coupon(
        spu_id=spu_id, name=name, points=points, price=price,
        status=status, down_time=down_time,
        reference_items=[], reference_total=ref, reference_source="menu",
    )


# ---------- parse_time ----------

def test_parse_time_supports_common_formats():
    assert parse_time("2026-12-30 23:59:59") == datetime(2026, 12, 30, 23, 59, 59)
    assert parse_time("2026-12-30 23:59") == datetime(2026, 12, 30, 23, 59)
    assert parse_time("2026-12-30") == datetime(2026, 12, 30)
    assert parse_time("") is None
    assert parse_time("not-a-date") is None


# ---------- 假上架过滤 ----------

def test_stale_coupons_are_filtered_even_if_status_says_active():
    """接口把 15 张过期券标成「上架」——过滤逻辑必须吃 downTime 而不是 status。"""
    fake_alive = coupon(spu_id=6113, down_time="2026-03-21 23:59:59")   # 已过期但 status=2
    fake_alive2 = coupon(spu_id=14931, down_time="2026-01-10 17:00:00")  # 同上
    alive = coupon(spu_id=17073, down_time="2026-12-30 23:59:59")

    active, stale = split_by_validity([fake_alive, fake_alive2, alive], NOW)
    assert [c.spu_id for c in active] == [17073]
    assert {c.spu_id for c in stale} == {6113, 14931}


def test_non_listed_status_is_filtered():
    active, stale = split_by_validity(
        [coupon(spu_id=1, status=3), coupon(spu_id=2, status=1)], NOW
    )
    assert active == []
    assert {c.spu_id for c in stale} == {1, 2}


def test_boundary_down_time_counts_as_active():
    """downTime 恰好等于当前时间不算过期（闭区间，与官方「截至当天」口径一致）。"""
    edge = coupon(spu_id=1, down_time="2026-10-14 12:00:00")
    active, _ = split_by_validity([edge], NOW)
    assert [c.spu_id for c in active] == [1]


# ---------- 排序 ----------

def test_rank_orders_by_efficiency_not_by_points():
    """12 倍差距就是这个测试要守住的东西。"""
    best = coupon(spu_id=17073, points=50, price=6.9, ref=13.5)     # 0.1320
    second = coupon(spu_id=17078, points=200, price=16.9, ref=29.0)  # 0.0605
    worst = coupon(spu_id=17075, points=100, price=3.9, ref=5.0)     # 0.0110

    ranked = rank([worst, second, best])
    assert [c.spu_id for c in ranked] == [17073, 17078, 17075]
    assert ranked[0].efficiency - ranked[-1].efficiency > 0.1


def test_rank_drops_unpriced_coupons():
    unpriced = coupon(spu_id=1, ref=None)
    priced = coupon(spu_id=2, ref=20.0)
    # 默认只给排过序的（有对照价的）券
    assert [c.spu_id for c in rank([unpriced, priced])] == [2]
    # 显式放开后，未核价的按效率 0 沉底
    assert [c.spu_id for c in rank([unpriced, priced], priced_only=False)] == [2, 1]


# ---------- 余额 ----------

def test_affordable_and_next_goal():
    pool = [
        coupon(spu_id=17073, points=50),
        coupon(spu_id=17078, points=200),
        coupon(spu_id=17081, points=800),
    ]
    assert [c.spu_id for c in affordable(pool, 536.8)] == [17073, 17078]
    goal = next_goal(pool, 386.8)
    assert goal is not None and goal.spu_id == 17081
    assert next_goal(pool, 900) is None


# ---------- 原始响应解析 ----------

def test_parse_coupons_reads_real_payload_shape():
    raw = {
        "success": True,
        "data": [
            {"spuName": "16.9元2份麦辣鸡翅", "spuId": 17078, "point": "200",
             "price": "0", "spuImage": "https://img.mcd.cn/ecs/x.jpg",
             "upTime": "2026-06-25 00:00:00", "downTime": "2026-12-30 23:59:59",
             "catName": "到店专用", "status": 2},
            {"spuName": "坏数据", "spuId": "abc", "point": "1", "status": 2},
        ],
    }
    ref = {"17078": {"referenceItems": [
        {"productCode": "1700", "productName": "麦辣鸡翅", "unitPrice": 14.5, "qty": 2}],
        "referenceTotal": 29.0, "referenceSource": "menu",
        "price": 16.9}}
    coupons = parse_coupons(raw, ref)
    assert len(coupons) == 1
    coupon_obj = coupons[0]
    assert coupon_obj.spu_id == 17078
    assert coupon_obj.points == 200
    assert coupon_obj.price == 16.9
    assert coupon_obj.reference_total == 29.0
    assert coupon_obj.save == 12.1
