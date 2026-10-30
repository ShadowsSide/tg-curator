# python:3.12-slim-bookworm 是多架构镜像（linux/amd64、linux/arm64），
# 在哪种机器上 build 就得到对应架构；也可以用 buildx 一次构建两种。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app
COPY requirements.txt .
# 所有依赖在 amd64/arm64 上都有预编译 wheel；--only-binary 保证不会意外走源码编译
RUN pip install --no-cache-dir --only-binary=:all: -r requirements.txt

COPY bot ./bot
RUN useradd --create-home app && mkdir -p /app/data && chown app:app /app/data
USER app

# 配置错误时机器人不退出（避免 Docker 反复重启），而是写下 /tmp/config-error 后待机：
# 健康检查据此显示 unhealthy，docker inspect 里能看到错误说明
HEALTHCHECK --interval=30s --timeout=5s --start-period=30s \
    CMD [ ! -f /tmp/config-error ] || { cat /tmp/config-error; exit 1; }

CMD ["python", "-m", "bot"]
