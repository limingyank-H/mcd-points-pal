"""积分宝 · 把麦当劳积分券搬进点餐流程。

包的入口。对外只暴露最常用的几个符号，方便:
    from mcd_points_pal import FixtureSource, build_plan
"""

from .datasource import FixtureSource, McpSource, normalize_menu
from .mcp_client import McpClient, McpError, extract_payload
from .models import Account, CartSummary, Coupon, Menu, MenuProduct, OrderLine
from .planner import build_plan, build_summary, efficiency_spread, parse_cart
from .points import affordable, next_goal, parse_coupons, rank, split_by_validity

__version__ = "1.0.0"

__all__ = [
    "FixtureSource",
    "McpSource",
    "McpClient",
    "McpError",
    "normalize_menu",
    "extract_payload",
    "Account",
    "Coupon",
    "Menu",
    "MenuProduct",
    "OrderLine",
    "CartSummary",
    "parse_cart",
    "build_summary",
    "build_plan",
    "efficiency_spread",
    "parse_coupons",
    "split_by_validity",
    "rank",
    "affordable",
    "next_goal",
    "__version__",
]
