# WorkBuddy 开发对话上下文 · 积分宝（McDonald's Points Pal）

> 本文件记录本项目使用 **腾讯 WorkBuddy** 开发时的对话上下文，用于核验是否符合麦当劳程序员节创意开发大赛的 **WorkBuddy 专项奖励**联动条件。

## 一、开发环境

| 项 | 值 |
|---|---|
| 开发工具 | 腾讯 WorkBuddy（Agent 模式） |
| 接入能力 | 麦当劳官方 MCP Server（`mcd-mcp`，`https://mcp.mcd.cn`） |
| 工作目录 | `<本地工作目录>` |
| 开发周期 | 2026-10-13 至 2026-10-14 |
| 产出 | 可交互 Demo、WorkBuddy Skill、免 Token CLI、参赛材料 |

WorkBuddy 在本项目中承担的角色：**MCP 调用与数据核验、竞品与赛道调研、方案设计与迭代、代码生成与调试、可视化 Demo 构建、参赛材料撰写**。

## 二、开发脉络

### 阶段 1 · 立项与赛道调研（10-13）

1. 抓取赛事仓库 README 与活动规则，确认：截止 10-25 23:59、以 GitHub 公开 Star 排名、前 100 名进入获奖范围、必交文件清单
2. 通过 WorkBuddy 已连接的 `mcd-mcp` 实测调用，确认 MCP 链路可用，并读取到账户积分（可用 536.8 分）
3. 用 GitHub 搜索逐条核查赛道饱和度，得到六个方向的竞品与天花板：

   | 方向 | 竞品数 | 赛道天花板 |
   |---|---|:--:|
   | 省钱 / 比价 | 17 | 256★ |
   | 派对 / 亲子 | 1（头部独占） | 208★ |
   | 碳足迹 | 1（方法学已被占位） | 206★ |
   | 营养 / 热量 | 10+ | 16★ |
   | 团餐 / 拼单 | 11 | 23★ |
   | 积分 / 权益 | 4 | 18★ |

   → **结论：常见功能维度已被占满，必须换"维度"而不是"功能"。**

### 阶段 2 · 方向三次迭代

| 版本 | 方向 | 放弃原因 |
|:--:|---|---|
| v1 | 麦麦时间账本（把时间成本算进价格） | 需要用户输入"时薪"才能运行；时薪是打工人专属参数，切掉学生群体；给的是认知不是能力 |
| v2 | 麦当劳的一天（按时段切换菜单） | 实测发现宵夜时段没有独立菜单（"2 套菜单"而非"5 套"），叙事被削弱 |
| v3 | **积分宝（点单时顺手把积分花掉）** | ✅ 采纳 |

### 阶段 3 · 用 MCP 实测取证（全部为真实调用）

- `query-nearby-stores` 定位门店（深圳科技园长园得来速 1420888，距离 84m）
- `query-meals` 拉取全量菜单（14 分类、110 商品）
- `mall-points-products(catRuleIds="1>4")` 拉取积分券 → **发现 24 张中 15 张 `downTime` 已过期但 `status` 仍返回「上架」**
- `mall-product-detail` 逐张核验券详情与 `skuId`
- `query-meals` 交叉核价，算出「每积分省多少」，得出 **12 倍效率差**
- `query-my-account` 读取账户：可用 536.8 / 累计 13611.4 / **已过期 915.6** / 本月将过期 91
- `calculate-price` 验证「券必须随单核销」这一机制，并踩到「无效商品编码被静默丢弃」的坑

### 阶段 4 · Demo 迭代（9 版）

| 版本 | 关键变化 |
|:--:|---|
| v1–v4 | 独立积分页形态，被指出"像独立模块、不像点餐入口" |
| v5 | 积分兑换移入下单流程（用户指出券是"随单使用"） |
| v6 | 去掉 AI 味的大标题宣传区，Logo 改用官方 Golden Arches 矢量路径 |
| v7 | 信息架构重构为「购物车 → 确认订单 → 已下单」三步 |
| v8 | 1:1 复刻真实麦当劳小程序下单页（含左侧分类栏、商品卡、底部购物条） |
| **v9** | **在真实下单页之上接入积分：积分兑换列表 + 券随单买单 + 下单后积分到账** |

### 阶段 5 · 工程验证

- 用无头浏览器对完整流程做自动化验证（加餐 → 加券 → 购物车 → 确认订单 → 提交 → 积分到账）
- 逐项核对金额：正常点单 ¥62.50 − 省 ¥12.10 = 实付 ¥50.40；用 200 分；本单得 50 分；余额 536.8 → 386.8
- 修复运行期缺陷：日期拼接运算符优先级导致的文案错误、窄屏布局溢出

## 三、WorkBuddy 在本项目中的具体作用

1. **MCP 编排**：由 WorkBuddy 直接调用麦当劳 MCP 完成门店定位、菜单拉取、券核验、账户读取与核价，全部数据真实可复现
2. **数据核验**：对接口返回结果做交叉验证（如用菜单单点价核算券的"省多少"），发现并记录官方文档未说明的接口行为
3. **方案迭代**：三个方向的可行性均由 WorkBuddy 用真实数据论证后取舍，而非主观判断
4. **代码产出**：Demo（HTML/CSS/JS）、WorkBuddy Skill（`SKILL.md`）、免 Token CLI（`points_value.py`）均由 WorkBuddy 生成与调试
5. **质量保障**：WorkBuddy 以无头浏览器对 Demo 做端到端自动化验证与截图比对

## 四、可复现的验证路径

```bash
# 免 Token 即可复现核心逻辑（内置实测数据快照）
git clone <本仓库地址>
cd mcd-points-pal
python3 -m mcd_points_pal list
python3 -m mcd_points_pal advise --cart 9900005456:1,P17078:1
python3 -m mcd_points_pal checkout --cart 9900005456:1,P17078:1
python3 -m mcd_points_pal report --out examples/points-report.html
```

接入真实 MCP 后，可在 WorkBuddy 中直接对话复现全链路（见 `SKILL.md`），或在 CLI 上验证：

```bash
export MCD_MCP_TOKEN=你的Token
python3 -m mcd_points_pal tools --live   # 列出 MCP 提供的全部 Tool
python3 -m mcd_points_pal list --live    # 真实数据跑效率榜
```

## 五、重构：从「原型」到「可运行 Skill」（2026-10-14 下午）

在核对官方 `activityGuidelines.md` 时确认：大赛提交物是 **Skill**（官方定义：「能够实现信息查询、
业务处理、决策辅助、内容生成、任务执行等目的的应用程序、智能体、插件、自动化流程、工作流
或其他软件功能模块」），且「参赛项目须**真实使用**麦当劳 MCP 能力」。

据此在 WorkBuddy 中完成以下重构：

1. **新增真实 MCP 客户端** `src/mcd_points_pal/mcp_client.py`：Streamable HTTP + JSON-RPC 2.0，
   零依赖，处理 `initialize` → `notifications/initialized` → `tools/call` 握手、
   `Mcp-Session-Id` 会话、SSE 与 JSON 双响应形态，以及麦当劳 MCP 在 JSON 前附加的
   `## Original Response` 说明段
2. **新增双数据源** `datasource.py`：`McpSource`（真调 `https://mcp.mcd.cn`）与
   `FixtureSource`（读 `fixtures/` 内固化的真实响应），返回同一套模型，上层无感
3. **新增方法学模块** `points.py`：`downTime` 假上架过滤、每积分效率排序（4 位小数精度，
   避免 12 倍差距被四舍五入抹平）、下一档目标计算
4. **新增推荐引擎** `planner.py` 与渲染层 `render.py`（终端表格 + 单文件 HTML 报告）
5. **固化 fixtures**：券列表、账户、门店菜单、历史订单、逐张券的现金对照价核价表
6. **补 38 个测试并新增 GitHub Actions**：覆盖协议层（内置假 MCP Server 验证握手与调用）、
   方法学、推荐引擎，以及参赛合规自检（必备文件齐全、声明文件未被改动、配置无真实凭证）
7. **结构调整**：原 `demo/index.html` 移入 `examples/order-flow.html`（标注为 UI 示意）；
   `examples/points-report.html` 改为由 CLI 实际生成；原 `scripts/points_value.py`
   （纯离线计算器，无法证明真实使用 MCP）由 `src/` 包取代并删除

## 六、说明

- 本项目全部开发过程在腾讯 WorkBuddy 中完成，麦当劳 MCP 通过 WorkBuddy 的「自定义连接器」接入
- 仓库中不含任何真实 Token、密钥或账号凭证
- 本文件仅用于核验 WorkBuddy 联动活动奖励条件

