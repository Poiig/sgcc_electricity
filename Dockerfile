# 应用镜像：仅包含代码（变化频繁，单独一层）
# 基础镜像从 Docker Hub 拉取
ARG BASE_IMAGE=docker.io/poiig/ha_sgcc_electricity:base
FROM ${BASE_IMAGE}

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV LANG=C.UTF-8
ENV SET_CONTAINER_TIMEZONE=true
ENV CONTAINER_TIMEZONE=Asia/Shanghai
ENV TZ=Asia/Shanghai

ARG VERSION
ARG BUILD_DATE
ENV VERSION=${VERSION:-latest}
ENV BUILD_DATE=${BUILD_DATE}
ENV PYTHON_IN_DOCKER='PYTHON_IN_DOCKER'

WORKDIR /app
COPY scripts/ /app/scripts/

RUN mkdir -p /data

CMD ["python3", "scripts/main.py"]
