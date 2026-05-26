# service/ — PM 需求自动化能力层

FastAPI 服务 + CLI 入口 + 业务 agents。

## 本地开发（不依赖 Docker）

```bash
cd service
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"

# 跑配置检查
python -m pm_workflow.cli info

# 跑测试
pytest

# 启 FastAPI（开发模式）
uvicorn pm_workflow.api.main:app --reload --port 8000
# 访问 http://localhost:8000/docs 看自动生成的 OpenAPI 文档
```

## 容器化（通过项目根 docker-compose.yml）

```bash
# 在项目根（workflow/）目录
docker compose up -d service
docker compose logs -f service
curl http://localhost:8000/health
```

## 目录结构

```
service/
├── pyproject.toml          # 依赖 + 工具配置
├── Dockerfile              # service 容器
├── pm_workflow/            # Python 包
│   ├── config.py           # pydantic-settings 读 .env
│   ├── api/                # FastAPI 路由
│   ├── agents/             # researcher / breakdown / prd_writer
│   ├── llm/                # router + langfuse 包装
│   ├── notion/             # Notion client
│   ├── scrapers/           # Playwright 爬虫
│   ├── retrievers/         # Qdrant 客户端
│   └── cli.py              # CLI 入口
└── tests/
```
