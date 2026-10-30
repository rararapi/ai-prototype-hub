FROM node:24.18.0-bookworm-slim@sha256:6f7b03f7c2c8e2e784dcf9295400527b9b1270fd37b7e9a7285cf83b6951452d AS node
FROM ghcr.io/astral-sh/uv:0.11.19 AS uv
FROM python:3.11.18-slim-bookworm@sha256:94a8fee35252d06ab75856f15f12c7bae67b10e8a6da93c7fded82b2610926cd

COPY --from=node /usr/local/bin/node /usr/local/bin/node
COPY --from=node /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=uv /uv /usr/local/bin/uv
RUN ln -s /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -s /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && apt-get update \
    && apt-get install -y --no-install-recommends ca-certificates curl git make gosu util-linux \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 developer \
    && useradd --uid 1000 --gid 1000 --create-home --shell /bin/bash developer \
    && install -d -o developer -g developer /opt/protohub-venv \
       /workspaces/protohub/apps/web/node_modules /workspaces/protohub/tests/e2e/node_modules \
    && mkdir -p /usr/local/share \
    && { python --version; node --version; npm --version; uv --version; \
         dpkg-query -W -f='${Package} ${Version}\n' ca-certificates curl git make gosu util-linux; \
       } > /usr/local/share/protohub-toolchain.txt

ENV UV_PROJECT_ENVIRONMENT=/opt/protohub-venv \
    UV_PYTHON_DOWNLOADS=never \
    UV_LINK_MODE=copy \
    PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 \
    HOME=/home/developer \
    USER=developer \
    LOGNAME=developer \
    PATH="/opt/protohub-venv/bin:$PATH"

COPY .devcontainer/entrypoint.sh /usr/local/bin/protohub-dev-entrypoint
RUN chmod 0755 /usr/local/bin/protohub-dev-entrypoint

WORKDIR /workspaces/protohub
# Root is used only by the fixed-volume initializer. Interactive/editor processes use
# remoteUser=developer; the entrypoint replaces itself with gosu developer and the CMD.
USER root
ENTRYPOINT ["/usr/local/bin/protohub-dev-entrypoint"]
CMD ["sleep", "infinity"]
