# 操作手册（PM 视角）

> 给「拿到这份代码想跑起来用」的同事看的速查手册。
> 项目本身介绍见 [README.md](./README.md)；架构 / 路线图 / Notion schema 细节见 [ROADMAP.md](./ROADMAP.md)。

---

## 一、它能帮你做什么

在 Notion 需求表新建一行需求 → 等 3-6 分钟 → 自动产出：

| 需求类型 | 产出 |
|---|---|
| **Build**（功能需求） | 竞品调研报告 + 需求拆解 + PRD（含 Critic 跨家审校） |
| **Discover**（探索调研） | 竞品/趋势调研报告 + 洞察备忘录（核心洞察/趋势/机会/风险/开放问题） |

所有产出会自动以 Notion 子页面形式生成，URL 回写到需求行；本地也会落一份在 `outputs/{req_id}/`。

---

## 二、首次部署（30 分钟）

### 准备工作

需要先有：

1. **Docker Desktop**（Mac/Windows/Linux 任一），并确保 `docker compose version` 可用
2. **Notion 工作区**，且有创建 Internal Integration 的权限
3. **LLM 网关 API Key**：本项目默认走 [modelverse.cn](https://api.modelverse.cn)（OpenAI 兼容协议，一个 token 接 Kimi/GLM/DeepSeek 多家），也可换成自家 OpenAI/Anthropic
4. **Tavily Search API Key**：免费档够用，注册即得 → [tavily.com](https://tavily.com)
5. **（可选）飞书群机器人 webhook**：用于状态变更通知，不配则只打 stdout

### 步骤 1：建 Notion 数据库

在 Notion 任意页面下，建 4 个子数据库（建议放同一个父页面，方便管理）。每个库的字段如下：

#### A. PM 需求表（触发源，必建）

| 字段名 | 类型 | 说明 |
|---|---|---|
| 需求名称 | Title | 必填 |
| 场景描述 | Text | 必填，越具体产出越准 |
| 需求类型 | Select | 选项：`Build` / `Discover` |
| 指定竞品 | Multi-select | Build 建议 1-3 个；Discover 可空 |
| 状态 | Select | 选项：`待处理` / `调研中` / `拆解中` / `PRD生成中` / `洞察生成中` / `已完成` / `失败` |
| 调研报告链接 | URL | 自动回填 |
| 需求拆解链接 | URL | 自动回填（Build 路径） |
| PRD链接 | URL | 自动回填（Build 路径） |
| 洞察备忘录链接 | URL | 自动回填（Discover 路径） |
| 失败原因 | Text | 自动回填 |
| req_id | Text | 自动生成 |
| 创建时间 | Created time | Notion 自动 |

#### B. Skill Library（Prompt 仓库）

只需要这 10 个字段（其他字段可有可无）：

`Name` (Title) / `Skill Key` (Text) / `Status` (Select) / `Version` (Text) / `Description` (Text) / `System Prompt` (Text) / `User Prompt Template` (Text) / `Input Variables` (Text，存 JSON) / `Output Schema` (Text，存 JSON) / `Model Preference` (Select：`auto`/`claude`/`gpt`/`moonshot`/`deepseek`)

服务首次启动会把 `skill-library/*.md` 同步进来，不用手动加。

#### C. 调研结果缓存

| 字段 | 类型 |
|---|---|
| 竞品名称 | Title |
| 最后调研时间 | Date |
| 缓存数据链接 | URL |
| 来源 | Select（公开网页 / 登录站抓取 / Perplexity）|
| req_id | Text |

#### D. Eval 数据集（Phase 7 用，可先空着）

| 字段 | 类型 |
|---|---|
| 用例名称 | Title |
| 输入需求 | Text |
| 金标PRD链接 | URL |
| 场景 | Select（调研 / 拆解 / PRD / 端到端） |
| 启用 | Checkbox |

### 步骤 2：建 Notion Integration 并把 4 个库分享给它

1. 浏览器打开 [www.notion.so/profile/integrations](https://www.notion.so/profile/integrations) → 新建一个 Internal Integration → 复制 `ntn_` 开头的 token
2. 回到 Notion，每个数据库右上角 `···` → `Add connections` → 选刚才建的 Integration
3. 每个数据库 URL 里 `https://notion.so/xxx?v=yyy` 的 `xxx` 段（32 位 hex）就是 DB ID，记下 4 个

### 步骤 3：填 .env

```bash
cp .env.example .env
```

打开 `.env` 填这些字段（其他可保留默认）：

```env
LLM_GATEWAY_TOKEN=<modelverse 或自家 LLM 网关的 token>
TAVILY_API_KEY=<tavily token>
NOTION_API_KEY=<ntn_ 开头>
NOTION_PARENT_PAGE_ID=<父页面 ID>
NOTION_DB_REQUIREMENTS=<A 库 ID>
NOTION_DB_SKILL_LIBRARY=<B 库 ID>
NOTION_DB_RESEARCH_CACHE=<C 库 ID>
NOTION_DB_EVAL=<D 库 ID>
FEISHU_WEBHOOK_URL=<可选，飞书群机器人 webhook>
```

> Postgres / n8n / Langfuse 的密码字段建议改成你自己的随机字符串。

### 步骤 4：启动

```bash
docker compose up -d
docker compose ps  # 应该看到 5 个容器 running
```

5 个容器：`pm_postgres` / `pm_n8n` / `pm_qdrant` / `pm_langfuse` / `pm_service`

### 步骤 5：激活 n8n 主流程

```bash
# 把 workflow JSON 导入 n8n
docker exec pm_n8n n8n import:workflow --input=/workflows/main.json

# 浏览器打开 http://localhost:5678 → 登录（账密见 .env）→ 找到 "PM 需求自动化主流程" → 右上角开关切 Active

# 激活后必须重启 n8n 才能生效
docker compose restart n8n

# 确认激活成功
docker exec pm_n8n n8n list:workflow --active=true
```

完成。可以去 Notion 需求表新建一行试试。

---

## 三、日常使用流程

### 提需求

在 Notion **需求表**新建一行，填：

- **需求名称**（必填）
- **场景描述**（必填，越具体效果越好；建议 100 字以上，描述用户/场景/目标）
- **需求类型**（必选 Build 或 Discover）
- **指定竞品**（Build 建议 1-3 个；Discover 可空，让系统自己找）
- **状态**：**必须显式选「待处理」** ← 不选不触发

### 等结果

- n8n 每 **2 分钟**轮询一次「待处理」状态的行
- 单需求耗时：**Build 路径 ~6 分钟**（research → breakdown → prd），**Discover 路径 ~3 分钟**（research → insight_memo）
- 状态会逐步翻：
  - Build：`待处理` → `调研中` → `拆解中` → `PRD生成中` → `已完成`
  - Discover：`待处理` → `调研中` → `洞察生成中` → `已完成`

实时监视：

```bash
docker logs -f pm_service | grep notifier
```

### 看产出

Notion 需求行里的链接字段会自动填好，点过去就行。本地也有一份在 `outputs/{req_id}/`。

---

## 四、异常处理速查

| 现象 | 处理 |
|---|---|
| 状态翻成「失败」 | 主行「失败原因」字段会写报错。改完场景/竞品后，状态改回「待处理」即可重跑 |
| 已完成的需求想重跑 | 状态改回「待处理」即可。本地 `outputs/{req_id}/*.md` 直接覆盖；Notion 子页面会**新建**（旧的孤儿留在 Notion，需手动清理） |
| 容器全死 | `docker compose up -d` |
| service 卡住不响应 | `docker compose restart service` |
| n8n 不触发新需求 | 检查激活：`docker exec pm_n8n n8n list:workflow --active=true`，重新激活后必须 `docker compose restart n8n` |
| LLM 报 `model_error` | 看 `.env` 的 `LLM_MODEL_*`，确认 modelverse 套餐含该模型；或换成 `LLM_GATEWAY_URL` + 自家 token |
| Notion 报 401 | Integration 没分享到那个数据库；去 Notion 每个库右上角 `Add connections` 加一下 |

---

## 五、改东西怎么改（脱离开发者维护）

**前置**：`cd /path/to/this/repo`

| 想改什么 | 改哪里 | 之后做什么 |
|---|---|---|
| Prompt（最常见） | `skill-library/{breakdown,discover,prd,research}/*.md` 的 System Prompt / User Prompt Template 段 | `docker compose restart service`（启动会自动 sync 到 Notion） |
| 换模型 | `.env` 的 `LLM_MODEL_*` | `docker compose restart service` |
| 飞书通知 | `.env` 加 `FEISHU_WEBHOOK_URL=...` | `docker compose restart service` |
| 看 LLM 调用日志 / 成本 | 浏览器开 `http://localhost:3000` Langfuse Dashboard | — |
| 看 n8n 流程可视化 | 浏览器开 `http://localhost:5678` | n8n 自动保存 |
| 加新 skill | `skill-library/` 下加 md 文件，frontmatter 用现有 skill 同款结构 | 重启 service 自动同步到 Notion |
| 加新需求类型 | 改 `service/pm_workflow/notion/models.py:RequirementType` enum + orchestrator 路由分支 | 重启 service + Notion schema 加 select 选项 |
| n8n 出问题时手动跑 | `docker exec -e PYTHONPATH=/app pm_service pm-workflow {research,breakdown,prd,insight} --page-id <uuid>` | — |

---

## 六、成本预估

| 路径 | Token 消耗 | 估算成本（modelverse 通用价） |
|---|---|---|
| Build（含 1 轮 critic 修订） | ~50-65k tokens | ~$0.5-1.5 / 需求 |
| Discover | ~4-8k tokens | ~$0.1 / 需求 |

`.env` 的 `COST_BUDGET_PER_REQUEST_USD` 是单需求预算上限（超出会熔断），默认 3。

---

## 七、已知限制

1. **重入仍可能浪费 research 阶段 ~3.5k tokens**：状态翻新偶发静默失败时 n8n 同窗口再扫一次。最贵的 PRD/insight 阶段已有 noop 守卫挡住。
2. **Critic 偏内部一致性**：评分不强反映事实密度，0 竞品需求可能得高分。
3. **重跑产生孤儿 Notion 子页面**：每次重跑新建子页面，旧的需手动清理。
4. **没有自动评估回归**：产出质量靠人看，无回归指标。

---

## 八、彻底弃用 n8n / 迁移

能力层是独立 FastAPI 服务，编排可任意替换：

- **cron 调 CLI**：`*/2 * * * * docker exec pm_service pm-workflow scan-new-requirements`
- **GitHub Actions / Lark / Slack 触发**：直接调 `http://localhost:8000/research|/breakdown|/prd|/insight`
- **迁移到新机器**：拷整个目录 → `cp .env.example .env` 填值 → `docker compose up -d` → 重新激活 n8n workflow

---

## 九、要帮助？

- 详细架构和每个 Phase 的设计决策：[ROADMAP.md](./ROADMAP.md)
- 提 Issue 描述：使用场景 + 报错日志（`docker logs pm_service` 最后 100 行）
