# MCP 集成说明

本项目基于麦当劳官方 **MCP Server（`mcd-mcp`，`https://mcp.mcd.cn`）** 开发，所有门店、菜单、价格、积分券与账户数据均来自实时接口调用，未使用任何虚构数据。

---

## 一、使用的 MCP Server

| 项 | 值 |
|---|---|
| Server 名称 | `mcd-mcp` |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | `streamablehttp` |
| 鉴权方式 | `Authorization: Bearer <MCP_TOKEN>`（Token 需自行到 [麦当劳 MCP 控制台](https://open.mcd.cn/mcp) 申请） |
| 脱敏配置示例 | 见 [`mcp-config.example.json`](mcp-config.example.json)（仅使用环境变量占位符） |

## 二、使用的 Tool 清单

| # | Tool | 用途 | 本项目中的角色 |
|:--:|---|---|---|
| 1 | `query-nearby-stores` | 查询附近门店（到店 / 得来速） | **锚定门店**：拿到 `storeCode` / `beCode` |
| 2 | `query-meals` | 查询门店菜单 | **取菜单与单点价**：也是计算「省多少」的基准 |
| 3 | `mall-points-products` | 查询积分商城商品券（`catRuleIds=1>4`） | **积分券数据源**：核心 |
| 4 | `mall-product-detail` | 查询积分商品详情 | **取 `skuId`**（兑换时必须用 `skuId`，不是 `spuId`） |
| 5 | `mall-create-order` | 积分商城兑换下单 | **兑换券**：返回 `couponId` / `couponCode` |
| 6 | `query-my-account` | 查询积分账户 | **余额、本月将过期积分**：驱动「已用/还能换什么」 |
| 7 | `query-my-coupons` | 查询我的券 | 已有资产盘点（**注意：不校验门店规则**） |
| 8 | `query-store-coupons` | 查询门店可用券 | 校验券在**本门店/本渠道**是否可用 |
| 9 | `auto-bind-coupons` | 自动绑定券 | 下单前把券绑到订单 |
| 10 | `calculate-price` | 订单核价 | **随单核销核价**：`items` 中带 `couponId` + `couponCode` 才能生效 |
| 11 | `create-order` | 创建订单 | 提交订单 |
| 12 | `order-list` | 历史订单 | 复盘「上一单当时能怎么用积分」 |
| 13 | `campaign-calendar` | 活动日历 | 时段性活动与积分加成信息 |
| 14 | `delivery-query-stores` / `delivery-query-addresses` | 麦乐送门店与地址 | 外送渠道的 `beCode` 来源 |

## 三、调用流程

```
① 锚定门店 ────────────────────────────────────────  MCP
   query-nearby-stores(searchType, beType, city, keyword)
   → storeCode / beCode / 距离 / 是否支持预约

② 取菜单与单点价 ──────────────────────────────────  MCP
   query-meals(storeCode, orderType, beType)
   → 全量分类与商品；每个商品的现价 = 后续算「省多少」的基准
   （可选：传 reservationDate 可拿到早餐/下午茶等时段菜单）

③ 取积分券并清洗 ──────────────────────────────────  MCP + 自建
   mall-points-products(catRuleIds="1>4")
   ├─ 过滤：downTime > now        ← 剔除「假上架」券（实测 62.5%）
   ├─ 核验：mall-product-detail(skuId)  ← 兑换要用的真正 ID
   └─ 交叉核价：query-meals 里的单点价
        → 省 = 单点价 − 券价
        → 每积分效率 = 省 ÷ 消耗积分        ← 本项目的核心指标

④ 取账户积分 ──────────────────────────────────────  MCP
   query-my-account()
   → availablePoint / currentMouthExpirePoint / expiredPoint

⑤ 组装建议 ────────────────────────────────────────  自建
   候选券 ∩ {积分 ≤ 余额} ∩ {未在本单中}
   按「每积分效率」降序 → 输出「这单还能用积分换」

⑥ 随单核销核价 ────────────────────────────────────  MCP
   calculate-price(items=[...], couponId, couponCode)
   ← 券必须在这里随单传入，否则不生效（这是本项目产品设计的根本依据）

⑦ 下单 ────────────────────────────────────────────  MCP
   create-order(...)  → 取餐码

⑧ 积分反馈 ────────────────────────────────────────  自建
   本单得分 → 余额更新 → 计算「下一档还差多少分」→ 下次目标券
```

**MCP 负责客观数据（门店 / 菜单 / 价格 / 券 / 积分），自建部分负责换算与推荐（效率排序、随单搭配、下次目标）。**

## 四、业务价值

1. **把「积分」从资产盘点变成交易动作**
   传统积分工具解决「我有哪些积分」，本项目解决「**这一单该怎么用积分**」——积分券是随单核销的，只有在下单那一刻的推荐才真正可执行。

2. **用官方价格数据消除「这套餐划不划算」的猜测**
   每张券的「省多少」都由 `query-meals` 的实时单点价交叉核价得出，不是估算。用户可以自己复算。

3. **把 12 倍的效率差摆到台面上**
   同样的积分，换不同券的价值差 12 倍。这个结论为「积分该怎么花」提供了可验证的依据。

4. **形成复购闭环**
   下单后的积分到账反馈会给出「下一档还差多少分、能换什么」，让积分从「一次性消耗品」变成「下次再来」的理由。

## 五、实测发现（官方文档未说明）

以下均为开发过程中用真实接口复现出来的行为，供其他开发者参考：

### 1. 积分券存在大量「假上架」

`mall-points-products(catRuleIds="1>4")` 返回 24 张餐品券，其中 **15 张 `downTime` 已过期，但 `status` 仍返回 `2`（上架）**。直接照单推荐，**62.5% 的券实际兑换不了**。
→ 必须自行以 `downTime` 与当前时间比对过滤。

### 2. 兑换用 `skuId`，不是 `spuId`

券列表返回的是 `spuId`，而 `mall-create-order` 兑换时需要 `skuId`，需先经 `mall-product-detail` 取回。
→ 直接用 `spuId` 兑换会失败。

### 3. `calculate-price` 对已下架商品编码「静默丢弃」

传入旧的可乐中杯编码 `3050`，接口**不报错**，直接把它从 `productList` 中移除，金额照常计算。
→ 会静默产出一个错误的价格，且没有任何报错可捕获。必须对返回的 `productList` 做条目数校验。

### 4. 外送与到店使用两套商品编码

同一份巨无霸：到店为 `1100`，外送为 `901100`。
→ 用错编码时接口不报错，仅返回 `productPrice: 0` 与空的 `productList`。

### 5. `beCode` 的规则分渠道

- 到店自取场景**传入 `beCode` 会直接报错**（应省略）
- 外送的 `beCode` 来自 `delivery-query-stores`
- 得来速的 `beCode` 来自 `query-nearby-stores`

### 6. 门店可用券必须用 `query-store-coupons`

`query-my-coupons` **不校验门店与渠道规则**，用它推荐券会推出「用户到店用不了」的券。
→ 涉及「这个券能不能在本店用」的判断，必须走 `query-store-coupons`。

### 7. `query-meals` 支持 `reservationDate`，菜单按时段切换

传 `2026-10-14 08:00` 会返回**早餐菜单**；同一家门店，08:00 为巨无霸核价直接返回「不可售」，12:00 返回 ¥25.50。
→ 菜单与可售状态是**按时段切换**的，做任何价格判断都需明确时间上下文。

### 8. `calculate-price` 返回金额单位为「分」

注意与部分接口返回「元」不一致，混用会导致价格差 100 倍。

## 六、安全与合规

- 仓库中**不包含任何真实 Token、密钥或账号凭证**；`mcp-config.example.json` 仅使用环境变量占位符 `${MCD_MCP_TOKEN}`
- 所有接口调用均通过官方 MCP Server 完成，**未绕过、未篡改任何官方下单流程**
- 项目输出的价格与券状态**以麦当劳官方渠道的实时结果为准**
- 本项目为参赛作品，**非麦当劳官方产品**
