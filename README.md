# PM 需求自动化系统

> Notion 需求表新增一行 → 自动完成「**竞品调研 + 需求拆解 + PRD 撰写**」三阶段产出，PRD 走跨家 LLM Critic 审校循环。
>
> 📖 **拿到代码想跑起来 / 日常使用 / 异常处理 → 直接看 [USAGE.md](./USAGE.md)**
> 🏗️ 架构 / 路线图 / Phase 决策记录 → [ROADMAP.md](./ROADMAP.md)

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

完整建库 + 部署步骤见 [USAGE.md](./USAGE.md)。三件事：

```bash
# 1. 配置环境变量
cp .env.example .env  # 填入 LLM / Tavily / Notion 凭据

# 2. 启动 5 个容器
docker compose up -d

# 3. 激活 n8n workflow
docker exec pm_n8n n8n import:workflow --input=/workflows/main.json
# 浏览器开 http://localhost:5678 切 Active，再 docker compose restart n8n
```

### 服务入口

| 服务 | 地址 | 凭据 |
|---|---|---|
| n8n（编排） | http://localhost:5678 | `.env` 的 `N8N_BASIC_AUTH_*` |
| Langfuse（LLM 观测） | http://localhost:3000 | 首次访问注册 |
| Qdrant（向量库） | http://localhost:6333/dashboard | 无 |
| Service API | http://localhost:8000/docs | 无 |

---

## 日常运维 / 异常处理 / 改 Prompt / 迁移

→ **全部在 [USAGE.md](./USAGE.md)** 第四、五、八节

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

## License

MIT — 见 [LICENSE](./LICENSE)。

⚠️ 所有 API Key 严禁入 git。`.env` 已在 `.gitignore` 内，请勿强制 add。
