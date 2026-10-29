#!/usr/bin/env bash
# 用 buildx 一次构建 linux/amd64 + linux/arm64 镜像并推送到镜像仓库。
# 用法：scripts/build-multiarch.sh ghcr.io/<你>/tg-curator:latest
# 需要先 docker login；在 x86 机器上构建 arm64（或反过来）依赖 QEMU，Docker Desktop 已自带。
set -euo pipefail

IMAGE="${1:?用法: $0 <镜像名:标签>}"
PLATFORMS="${PLATFORMS:-linux/amd64,linux/arm64}"
cd "$(dirname "$0")/.."

docker buildx inspect tg-multiarch >/dev/null 2>&1 || docker buildx create --name tg-multiarch --use
docker buildx use tg-multiarch
docker buildx build --platform "$PLATFORMS" -t "$IMAGE" --push .
docker buildx imagetools inspect "$IMAGE"
