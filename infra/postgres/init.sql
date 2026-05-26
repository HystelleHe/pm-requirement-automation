-- postgres 容器首次启动时建两个 database
-- n8n 和 langfuse 各用一个，避免 schema 冲突
CREATE DATABASE n8n;
CREATE DATABASE langfuse;
