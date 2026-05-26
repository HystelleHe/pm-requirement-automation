# PM 需求自动化系统 - 能力层 FastAPI 服务
# 单阶段构建：Python 3.12-slim 基础 + 依赖 + 应用代码

FROM python:3.12-slim

# 系统依赖：curl 用于 healthcheck，build-essential 给某些 wheel 编译
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# 先复制依赖声明，利用 Docker 层缓存
COPY pyproject.toml ./
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -e .

# 复制应用代码
COPY pm_workflow ./pm_workflow

# 让 config.py 的路径计算锁定到 /app（skill-library / outputs 在这里 mount）
ENV PROJECT_ROOT=/app

EXPOSE 8000

# 容器内健康检查 —— compose 也会用同样路径
HEALTHCHECK --interval=15s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS http://localhost:8000/health || exit 1

# 启动：uvicorn 跑 FastAPI app
CMD ["uvicorn", "pm_workflow.api.main:app", "--host", "0.0.0.0", "--port", "8000"]
