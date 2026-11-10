# t3code at the pinned commit with every patch in clients/t3code/patches, Pi with the
# Hone extension, and the office tools the agent runs (pdftotext, python-docx, soffice).

FROM node:26.12.1-trixie-slim AS build
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 make g++ \
 && rm -rf /var/lib/apt/lists/*
RUN npm install -g vite-plus@1.4.0

ARG T3CODE_REPO=https://github.com/pingdotgg/t3code
ARG T3CODE_COMMIT=ac8dce0cc3abd8a337f2d806b5082a6834b9b81a
WORKDIR /opt/t3code
RUN git init -q . \
 && git fetch -q --depth 1 "$T3CODE_REPO" "$T3CODE_COMMIT" \
 && git checkout -q FETCH_HEAD
COPY clients/t3code/patches/ /tmp/patches/
RUN git -c user.name=build -c user.email=build@localhost am -q /tmp/patches/*.patch
ENV CI=true
RUN vp i --filter t3... --filter @t3tools/web...
RUN cd apps/web && vp build

FROM node:26.12.1-trixie-slim
RUN apt-get update \
 && apt-get install -y --no-install-recommends ca-certificates git python3 python3-docx \
      poppler-utils libreoffice-writer-nogui fonts-liberation \
 && rm -rf /var/lib/apt/lists/*
ARG PI_VERSION=1.5.0
RUN npm install -g "@earendil-works/pi-coding-agent@$PI_VERSION" && npm cache clean --force

COPY --from=build /opt/t3code /opt/t3code
COPY deploy/t3code/settings.json deploy/t3code/settings.py deploy/t3code/pi-settings.json deploy/t3code/entrypoint.sh /opt/hone-deploy/
COPY --chown=node:node deploy/t3code/pi-settings.json /home/node/.pi/agent/settings.json
COPY --chown=node:node clients/pi-extensions/hone.ts /home/node/.pi/agent/extensions/hone.ts
RUN install -d -o node -g node /home/node/.t3 /home/node/.pi/agent/sessions /home/node/demo

USER node
ENV T3CODE_HOME=/home/node/.t3 \
    T3CODE_NO_BROWSER=true \
    T3CODE_TELEMETRY_ENABLED=false \
    HONE_DEMO_DIR="/home/node/demo/Offer letters"
EXPOSE 3773
ENTRYPOINT ["/opt/hone-deploy/entrypoint.sh"]
