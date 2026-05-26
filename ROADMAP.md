# PM 需求自动化系统 - Roadmap

> 项目目标：Notion 触发 → 自动完成「竞品调研 → 需求拆解 → PRD 撰写」三阶段产出
> 最后更新：2026-05-26

---

## ⚡ Next Step（下次回到项目先看这里）

**当前状态**：Phase 0 实施中 — 项目骨架 + Notion 4 库已完成，**等待用户提供其余 5 个 API Key 后 Phase 0 全部结束**

**下一步动作**：
1. ⏳ 用户提供 ANTHROPIC / OPENAI / PERPLEXITY / DEEPSEEK / TAVILY 5 个 API Key 填入 `.env`
2. ⏳ Phase 0 收尾：git commit + 把本章节 checkbox 全部打勾
3. ⏳ 进入 Phase 1（能力层骨架 + Skill Library 同步）

**已完成**（2026-05-26）：
- ✅ 项目骨架 + git init + 目录结构
- ✅ `docker-compose.yml`（postgres + n8n + qdrant + langfuse 4 容器；service 待 Phase 1 启用）
- ✅ `.env.example` + `README.md` + `infra/postgres/init.sql`
- ✅ Notion 4 个数据库（3 个新建 + 1 个复用 workspace 顶层已有的 Skill Library）
- ✅ `NOTION_API_KEY` + 4 个 DB ID 写入 `.env`

---

## 📋 Roadmap（分阶段实施清单）

总工期约 **9-10 天**。建议 Phase 0-6 必做，Phase 7 二期。

- [ ] **Phase 0 - 脚手架（0.5 天）**
  - [x] 写 `docker-compose.yml`（n8n + service + Qdrant + Langfuse + PostgreSQL）
  - [x] 在 Notion 建 4 个数据库（3 新建 + 1 复用 Skill Library），Database ID 写入 `.env`
  - [ ] 配置所有 API Key（Claude / OpenAI / Perplexity / DeepSeek / Tavily / Notion — Notion 已完成）

- [ ] **Phase 1 - 能力层骨架 + Skill Library（1 天）**
  - [ ] FastAPI 项目结构 + Notion client + LLM router（含 Langfuse 中转）
  - [ ] 现有 Prompt 整理到 `skill-library/*.md`（frontmatter 只声明本项目用的 10 个字段，见 schema B）
  - [ ] 服务启动时单向同步 `skill-library/` → Notion Skill Library（**只读写 10 字段子集，不动其他列**）
  - [ ] CLI 入口能跑通"读 Notion 需求 → 打印场景"

- [ ] **Phase 2 - 调研 Agent（2 天）**
  - [ ] Perplexity 关键词发现
  - [ ] Playwright 登录站爬虫（先做 1 个站点）
  - [ ] Claude Sonnet 结构化总结
  - [ ] 产出写到 `outputs/{req_id}/research.md` + Notion 链接

- [ ] **Phase 3 - 需求拆解 Agent（1 天）**
  - [ ] 读取调研结果 + 拆解 Prompt → 用户故事 + 优先级
  - [ ] 产出写到 `outputs/{req_id}/breakdown.md`

- [ ] **Phase 4 - PRD Agent + Critic（2 天）**
  - [ ] 分章节生成 PRD（背景/目标/用户故事/功能/非功能）
  - [ ] GPT-4 Critic → Claude 修订循环（最多 2 轮）
  - [ ] 产出写到 `outputs/{req_id}/prd.md`

- [ ] **Phase 5 - 向量库 + Few-shot（1 天）**
  - [ ] Qdrant 索引：历史调研/PRD 入库（按场景分 collection）
  - [ ] 调研和 PRD agent 增加 retrieval 节点

- [ ] **Phase 6 - n8n 串联 + 通知（1 天）**
  - [ ] 主 workflow JSON + 飞书通知
  - [ ] 端到端跑通 3 个真实需求

- [ ] **Phase 7 - Eval（二期，1 天）**
  - [ ] 维护 5 个金标用例
  - [ ] `python -m pm_workflow.eval` 跑分

---

## 🏗 核心架构（一图说清）

**「编排层 + 能力层」分离**，确保可迁移、可脱离 Claude 独立维护。

```
Notion 需求表 (触发源)
       │ Webhook
       ▼
┌─────────────────────────────────┐
│  编排层：n8n (Docker)            │
│  只做：触发 / 状态机 / HTTP 调用 │
│  不放业务逻辑                    │
└──────────────┬──────────────────┘
               │ HTTP REST API
               ▼
┌─────────────────────────────────┐
│  能力层：FastAPI 服务 (Docker)   │
│  POST /research                  │
│  POST /breakdown                 │
│  POST /prd/generate (含 Critic)  │
│  POST /skills/search             │
│  + CLI 入口（脱离 n8n 也能用）   │
└──────────────┬──────────────────┘
               │
       ┌───────┼────────┬────────┐
       ▼       ▼        ▼        ▼
    Notion  Qdrant  Langfuse  LLM 厂商
```

**可迁移性保障**：
- 整个系统 = 5 个 Docker 容器 + 1 份 `docker-compose.yml`
- 能力层是标准 FastAPI 服务（自动 OpenAPI 文档），换 n8n 为任何编排工具都不影响
- CLI 入口是兜底：完全脱离 n8n 也能从命令行触发完整流程
- Prompt SoT 在本地 Markdown，Notion 只做展示镜像

---

## ✅ 已确认的关键决策

| 决策点 | 选择 |
|---|---|
| MVP 范围 | 竞品调研 + 需求拆解 + PRD（暂不做 Figma） |
| n8n 部署 | self-hosted Docker |
| 触发方式 | Notion 需求表新增行 |
| 工作流形态 | 全自动端到端（中间产物落 Notion，可独立 review） |
| LLM 模型 | 多模型混搭（见下表） |
| Skill Library | 现有部分 Prompt + 本地 md 为 SoT + Notion 镜像 |
| 竞品调研深度 | 指定竞品 + 关键词自动发现 + 登录站抓取 |
| 架构分层 | n8n 编排 + FastAPI 能力层（保证可迁移） |
| 优化点 | 全部纳入：向量库/Critic/MD存正文/三阶段/Langfuse/Eval |

**多模型路由**：

| 任务 | 模型 |
|---|---|
| 关键词→竞品发现 | Perplexity |
| 公开网页摘要 | Tavily + DeepSeek |
| 登录站抓取清洗 | Playwright + DeepSeek |
| 结构化总结 / 需求拆解 | Claude Sonnet |
| PRD 长文 | Claude Opus |
| PRD Critic | GPT-4 |
| Eval Judge | Claude Sonnet |

---

## 📁 项目目录结构（实施时的目标）

```
pm-workflow/
├── docker-compose.yml          # 整个系统的可迁移单元
├── .env.example
├── README.md                   # 启动 + 维护 + 迁移说明
├── n8n/workflows/              # n8n workflow JSON（Git 管理）
├── service/                    # 核心能力层（FastAPI）
│   ├── pm_workflow/
│   │   ├── api/                # FastAPI 路由
│   │   ├── agents/             # researcher / breakdown / prd_writer
│   │   ├── retrievers/         # Qdrant 客户端
│   │   ├── scrapers/           # Playwright 爬虫
│   │   ├── notion/             # Notion client
│   │   ├── llm/                # router + langfuse_wrapper
│   │   └── cli.py              # 脱离 n8n 的兜底入口
│   └── tests/
├── skill-library/              # Prompt SoT
│   ├── research/
│   ├── breakdown/
│   └── prd/
├── eval/                       # 金标用例 + judge
└── outputs/                    # 自动产出（gitignored，目录结构保留）
    └── {req_id}/
        ├── research.md
        ├── breakdown.md
        └── prd.md
```

**质量决定性文件**（重点关注）：
- `service/pm_workflow/agents/prd_writer.py` - PRD 生成 + Critic 循环
- `service/pm_workflow/llm/router.py` - 多模型路由
- `service/pm_workflow/cli.py` - 脱离 n8n 兜底入口
- `skill-library/**.md` - 所有 Prompt 本体
- `docker-compose.yml` - 可迁移单元

---

## 📊 Notion 数据库 schema（4 个库）

> 4 个数据库**已建好**，ID 在 `.env`。下面记录每个库的实际 schema，作为开发参考。父页面 ID：`NOTION_PARENT_PAGE_ID` = `36c0820f-9dba-80cd-8d80-c2583a6db942`。

**A. PM 需求表（触发源）** — `NOTION_DB_REQUIREMENTS`
- 需求名称(Title) / 场景描述(Text) / 指定竞品(Multi-select) / 自动发现关键词(Text)
- 状态(Select: 待处理/调研中/拆解中/PRD生成中/已完成/失败)
- 调研报告链接(URL) / 需求拆解链接(URL) / PRD链接(URL) / 失败原因(Text)
- req_id(Text) — 对应 `outputs/{req_id}/` 目录
- 创建时间(Created time，Notion 自动)

**B. Skill Library（复用 workspace 顶层共享资产）** — `NOTION_DB_SKILL_LIBRARY`
- 这个库**早于本项目存在**（2026-04-29 建），是用户的通用 Prompt 仓库，30+ 字段企业级 schema
- 本项目**只读写一个 10 字段子集**，其他列保留给原有用途，本项目代码不动它们
- 本项目使用的字段子集：
  - `Name` (Title) / `Skill Key` (Text) / `Status` (Select) / `Version` (Text)
  - `Description` (Text) / `System Prompt` (Text) / `User Prompt Template` (Text)
  - `Input Variables` (Text，JSON) / `Output Schema` (Text，JSON)
  - `Model Preference` (Select: auto/claude/gpt/moonshot/deepseek)
  - `适用管线` (Multi-select: 竞品调研/PRD/Figma)
- 本地 `skill-library/*.md` 文件的 frontmatter **只声明上面 10 个字段**，启动同步时**只读写这 10 列**

**C. 调研结果缓存** — `NOTION_DB_RESEARCH_CACHE`（同竞品 24h 内复用）
- 竞品名称(Title) / 最后调研时间(Date) / 缓存数据链接(URL)
- 来源(Select: 公开网页/登录站抓取/Perplexity) / req_id(Text)

**D. Eval 数据集** — `NOTION_DB_EVAL`
- 用例名称(Title) / 输入需求(Text) / 金标PRD链接(URL)
- 场景(Select: 调研/拆解/PRD/端到端) / 启用(Checkbox)

---

## ⚠️ 已识别的风险与缓解

| 风险 | 缓解策略 |
|---|---|
| 编排层+能力层双层维护，初期复杂度高 | FastAPI 自动文档；n8n 节点保持简单（只有 HTTP） |
| Qdrant 数据冷启动效果差 | 前 10 次需求人工标记好坏，把好的归档入库 |
| Critic 循环可能死循环 | 硬限制最多 2 轮 + token budget 上限 |
| Notion API 限速 | 加 retry + 队列；非热路径写入合并 |
| Skill Library 双写不一致 | 启动时校验本地 md 与 Notion 的 hash，本地为准 |
| 登录站爬虫被风控 | 用真实账号 Cookie + 低频率（>30s 间隔）+ 失败降级到只用公开数据 |
| LLM 成本失控 | n8n 加 Token 计数器，单次需求 > $1 告警 |

---

## 🔧 维护说明（脱离 Claude 后怎么搞）

### 日常运维
- **看错误**：n8n UI 执行历史 + Notion 需求表「失败原因」字段
- **看成本**：Langfuse Dashboard
- **看产出**：`outputs/` 目录或 Notion URL 跳转

### 加新能力
- **新爬虫**：在 `service/pm_workflow/scrapers/` 加文件，继承 `base.py`
- **改 Prompt**：改 `skill-library/xxx.md` → 重启服务自动同步到 Notion → 跑 eval 防回归
- **新阶段**：在 `agents/` 加文件 → FastAPI 路由注册 → n8n 加节点调用

### 迁移到新机器
1. 拷贝整个 `pm-workflow/` 目录
2. 复制 `.env.example` → `.env` 填值
3. 在新环境建 Notion 4 个库（schema 见上）
4. `docker-compose up`

### 完全弃用 n8n
能力层是独立 FastAPI 服务，可用：
- cron 调 CLI：`*/30 * * * * python -m pm_workflow.cli scan-new-requirements`
- GitHub Actions 触发
- 包装成 Slack/飞书机器人
- 直接 curl

---

## 🧪 验证方式（实施完成后跑）

**端到端**：
1. Notion 新增需求行
2. n8n UI 观察子流程依次成功
3. Langfuse 看到所有 LLM trace，单次成本 < $1
4. `outputs/{req_id}/` 有 3 个 md 文件
5. Notion 状态变「已完成」，3 个 URL 字段填充

**可迁移性测试**：拷贝目录到新机器，只改 `.env`，能跑通

**脱离 Agent 维护测试**：不用 Claude Code，加一个新竞品爬虫 + 改 PRD prompt 跑 eval

---

## 📜 协作规则

### 规则 1：每完成一部分，用 git 进行版本管理
- **粒度**：每完成一个 Roadmap 中的 Phase（或 Phase 内一个独立可验证的子任务）就 commit 一次
- **要求**：
  - 项目根目录 `pm-workflow/` 是 git 仓库
  - commit message 写清楚做了什么（建议遵循 `<type>: <description>` 格式，type 如 feat/fix/docs/refactor/test）
  - 不允许把多个 Phase 的改动堆到一个 commit
- **目的**：随时可回滚；进度可追溯；脱离 Claude 后能 `git log` 看到每一步做了什么

### 其他规则
> 待用户补充（暂未定义代码风格、prompt 写法、AI 协作边界等规则）

---

## 📚 参考资料

- **完整原始 plan**（包含详细推理过程）：`/Users/hystelle/.claude/plans/n8n-notion-glittery-church.md`
- 本文档是该 plan 的精炼版，作为日常 roadmap 入口
