# fixtures · 真实 MCP 响应的固化样本

这些文件是麦当劳 MCP 的**真实返回值**，在 2026-10-14 通过 `https://mcp.mcd.cn` 采集。
它们的作用是让这个仓库 **clone 下来零配置就能跑**——不需要申请 Token 也能复现
积分券效率榜和推荐结果。

| 文件 | 来源 Tool | 说明 |
|---|---|---|
| `points_products.json` | `mall-points-products` | 24 张「商品券」，**其中 15 张 downTime 已过但仍 status=2（上架）**——本项目要处理的「假上架」就在这份原始数据里 |
| `my_account.json` | `query-my-account` | 麦享会积分账户。accountId 已脱敏 |
| `menu_1420888.json` | `query-meals` | 深圳科技园长园得来速餐厅的完整菜单，14 分类 / 110 商品 |
| `coupon_reference.json` | 人工核价表 | 每张积分券的「现金对照价」，依据门店菜单单点价逐张核算，可逐条审计 |
| `orders.json` | `order-list` | 历史订单，用于「复盘上单错过了什么」。orderId 已脱敏 |

## 为什么需要 `coupon_reference.json`

麦当劳 MCP 不提供「这张券值多少钱」的换算——它只给券名（如「16.9元2份麦辣鸡翅」）。
要算「省多少」，必须把券和门店菜单里的真实单点价做一次对照：

```
对照价 = 麦辣鸡翅单点 ¥14.5 × 2 = ¥29.0
券价   = ¥16.9（券名里的数字）
省     = ¥29.0 − ¥16.9 = ¥12.1
每积分效率 = ¥12.1 ÷ 200 分 = ¥0.0605
```

这是本项目**唯一带人工判断的环节**，所以我们把它写成一张显式的表，
每个对照商品都带 `productCode`，能直接在 `menu_1420888.json` 里查到并复核。
（有 CI 测试保证：对照表里引用的每个编码都必须真实存在于菜单。）

## 重新采集

```bash
export MCD_MCP_TOKEN=你的token
python -m mcd_points_pal list --live
```

fixtures 不会自动更新——它们是快照，用来保证结果可复现。
