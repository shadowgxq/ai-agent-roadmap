# Coding Agent 的最小执行镜像：代码通过 bind mount 注入，不把宿主仓库复制进镜像。
FROM python:3.12-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
    && apt-get install --no-install-recommends --yes ca-certificates git \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 agent \
    && useradd --uid 10001 --gid 10001 --create-home --shell /usr/sbin/nologin agent \
    && mkdir --parents /workspace /tmp \
    && chown --recursive agent:agent /workspace /tmp

WORKDIR /workspace
USER 10001:10001

# DockerExecutor 会在运行时覆盖 network、filesystem、PID、CPU、memory 和 timeout。
ENTRYPOINT ["/bin/sh"]
