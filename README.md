# PM 需求自动化系统（workflow）

> Notion 触发 → 自动完成「**竞品调研 + 需求拆解 + PRD 撰写**」三阶段产出
> 详细计划见 [ROADMAP.md](./ROADMAP.md)

---

## 架构总览

```
Notion 需求表 → n8n（编排）→ FastAPI 服务（能力层）→ Notion / Qdrant / Langfuse / LLM
```

- **编排层**：n8n（Docker），只做触发/状态机/HTTP 调用
- **能力层**：FastAPI 服务（Docker），所有业务逻辑 + CLI 兜底入口
- **数据**：Notion（4 个库）+ Qdrant 向量库 + Langfuse 观测
- **可迁移**：一份 `docker-compose.yml` + 一份 `.env` 完整迁移

---

## 快速启动

### 1. 准备环境

```bash
# 复制环境变量模板
cp .env.example .env
# 编辑 .env 填入所有 API Key 和 Notion DB ID
```

需要准备的 API Key：
- Anthropic（Claude）/ OpenAI（GPT-4）/ Perplexity / DeepSeek / Tavily
- Notion Internal Integration Token

需要在 Notion 建的 4 个数据库（schema 见 ROADMAP.md「📊 Notion 数据库 schema」）：
- 需求表 / Skill Library / 调研结果缓存 / Eval 数据集

### 2. 启动容器

```bash
docker compose up -d
docker compose ps   # 检查所有容器健康
```

### 3. 访问入口

| 服务 | 地址 | 默认凭据 |
|---|---|---|
| n8n | http://localhost:5678 | 见 `.env` 的 `N8N_BASIC_AUTH_*` |
| Langfuse | http://localhost:3000 | 首次访问注册即可 |
| Qdrant | http://localhost:6333/dashboard | 无认证 |
| Service API（Phase 1 后启用） | http://localhost:8000/docs | 无认证 |

---

## 日常运维（脱离 Claude 后怎么搞）

- **看错误**：n8n UI 执行历史 + Notion 需求表「失败原因」字段
- **看成本**：Langfuse Dashboard
- **看产出**：`outputs/{req_id}/` 目录或 Notion URL 跳转
- **改 Prompt**：改 `skill-library/xxx.md` → 重启 service 自动同步到 Notion → 跑 eval 防回归
- **加新爬虫**：在 `service/pm_workflow/scrapers/` 加文件，继承 `base.py`
- **加新阶段**：`agents/` 新增 → FastAPI 路由注册 → n8n 加 HTTP 节点

---

## 迁移到新机器

1. 拷贝整个项目目录
2. `cp .env.example .env` 填值
3. 新环境 Notion 建 4 个库（schema 见 ROADMAP.md）
4. `docker compose up -d`

---

## 完全弃用 n8n

能力层是独立 FastAPI 服务，可任意替换编排方式：
- cron 调 CLI：`*/30 * * * * docker compose exec service python -m pm_workflow.cli scan-new-requirements`
- GitHub Actions 触发
- 包装成 Slack/飞书机器人
- 直接 `curl localhost:8000/...`

---

## 目录结构

```
workflow/
├── docker-compose.yml          # 迁移单元
├── .env.example                # 环境变量模板
├── README.md                   # 本文件
├── ROADMAP.md                  # 完整计划 + Next Step
├── infra/postgres/init.sql     # postgres 初始化脚本
├── n8n/workflows/              # n8n workflow JSON
├── service/                    # FastAPI 能力层（Phase 1 起）
│   └── pm_workflow/
│       ├── api/                # FastAPI 路由
│       ├── agents/             # researcher / breakdown / prd_writer
│       ├── retrievers/         # Qdrant 客户端
│       ├── scrapers/           # Playwright 爬虫
│       ├── notion/             # Notion client
│       └── llm/                # router + langfuse_wrapper
├── skill-library/              # Prompt SoT（本地 md 为准）
│   ├── research/
│   ├── breakdown/
│   └── prd/
├── eval/                       # 金标用例 + judge
└── outputs/{req_id}/           # 自动产出（不入 git）
```

---

## 协作规则

- **每完成一个 Phase（或 Phase 内独立可验证子任务），git commit 一次**
- commit message 遵循 `<type>: <description>`（type 如 `feat/fix/docs/refactor/test`）
- 进度追踪在 `ROADMAP.md` 的 checkbox

---

## License & 责任

仅供内部使用，所有 API Key 严禁入 git。
