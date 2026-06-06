# 阶段 1：Python 依赖（仅在 requirements.txt 变化时重建）
ARG BASE_IMAGE=ghcr.io/poiig/ha_sgcc_electricity:base
FROM ${BASE_IMAGE} AS pip-deps

COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=cache,target=/root/.cache/pip \
    pip install --upgrade pip \
    && PIP_ROOT_USER_ACTION=ignore pip install \
    --disable-pip-version-check \
    -r /tmp/requirements.txt \
    && rm -rf /tmp/requirements.txt

# 阶段 2：应用代码（变化最频繁，单独一层）
FROM pip-deps

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
COPY scripts/ /app/

RUN mkdir -p /data

CMD ["python3", "main.py"]
