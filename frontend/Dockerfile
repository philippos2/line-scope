FROM node:24-bookworm-slim@sha256:d6aa754f16b3197301076f047b5def2f02ea1dbbc2ca920407d46d7ec7f87b20 AS dependencies
WORKDIR /app
RUN chown node:node /app
USER node
COPY --chown=node:node package.json package-lock.json ./
RUN npm ci

FROM dependencies AS development
COPY --chown=node:node . .
EXPOSE 5173
CMD ["npm", "run", "dev"]

FROM dependencies AS browser-dependencies
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
USER root
RUN npx playwright install --with-deps chromium && chmod -R a+rX /opt/playwright
USER node

FROM browser-dependencies AS browser-check
COPY --chown=node:node . .
