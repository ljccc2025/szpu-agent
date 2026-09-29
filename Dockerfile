# M22 部署镜像：多阶段构建（builder 装依赖并预热模型 -> runtime 只带运行产物）。
#
# 目标虚拟机（Rocky Linux 8.9）实测到的两条硬约束：
#   1) pypi.org 不可达 —— pip 源必须写死清华镜像，否则构建会卡死；
#   2) python:3.11-slim 已在本地缓存 —— 构建不再拉取，规避镜像源抖动。
#
# 模型在构建期烘焙进镜像：答辩现场断网也能启动，对应非功能需求「演示零翻车」。
#
# 注意：刻意不写 `# syntax=docker/dockerfile:1` —— 该指令会让 BuildKit 去
# Docker Hub 拉 dockerfile 前端镜像，而目标机拉取不稳会直接卡住构建。
# 本文件只用了内置语法即可支持的特性，不需要外部前端。

ARG PIP_INDEX_URL=https://pypi.tuna.tsinghua.edu.cn/simple

# ---------------- builder：装依赖 + 预热模型 ----------------
FROM python:3.11-slim AS builder

ARG PIP_INDEX_URL
ENV PIP_INDEX_URL=${PIP_INDEX_URL} \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /build

# 先单独装 CPU 版 torch：否则 sentence-transformers 会拖进 2.5GB 的 CUDA 包。
# 这一层独立于 requirements.txt，改业务依赖时不会让 torch 重下。
RUN pip install --user --no-warn-script-location \
        torch --index-url https://download.pytorch.org/whl/cpu

COPY requirements.txt .
RUN pip install --user --no-warn-script-location -r requirements.txt

# 构建期把 bge-small-zh-v1.5（约 93MB）下进镜像，运行时零下载、可离线演示
ENV HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/opt/hf \
    PYTHONPATH=/root/.local/lib/python3.11/site-packages
RUN python -c "from sentence_transformers import SentenceTransformer; \
SentenceTransformer('BAAI/bge-small-zh-v1.5')"

# ---------------- runtime：只带运行所需 ----------------
FROM python:3.11-slim AS runtime

# curl 供 HEALTHCHECK 使用；顺手建非 root 用户
RUN apt-get update \
 && apt-get install -y --no-install-recommends curl \
 && rm -rf /var/lib/apt/lists/* \
 && useradd -m -u 1000 app

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    HF_ENDPOINT=https://hf-mirror.com \
    HF_HOME=/opt/hf \
    PATH=/home/app/.local/bin:$PATH \
    PYTHONPATH=/home/app/.local/lib/python3.11/site-packages

COPY --from=builder --chown=app:app /root/.local /home/app/.local
COPY --from=builder --chown=app:app /opt/hf /opt/hf

WORKDIR /app
COPY --chown=app:app app/ ./app/
COPY --chown=app:app static/ ./static/

# data/ 由 compose 卷挂载进来，这里只预建目录并移交属主
RUN mkdir -p /app/data && chown app:app /app/data

USER app
EXPOSE 8000

# start-period 给足 40 秒：首次启动要把嵌入模型载入内存
HEALTHCHECK --interval=15s --timeout=5s --start-period=40s --retries=3 \
  CMD curl -fsS http://localhost:8000/api/health || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
