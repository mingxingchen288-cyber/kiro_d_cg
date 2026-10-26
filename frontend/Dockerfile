FROM node:20-bookworm-slim AS build

WORKDIR /app

RUN corepack enable && corepack prepare pnpm@10.5.0 --activate

COPY package.json pnpm-lock.yaml pnpm-workspace.yaml .npmrc ./
COPY build build
COPY packages packages
COPY public public
COPY src src
COPY index.html tsconfig.json uno.config.ts vite.config.ts eslint.config.js ./
COPY .env .env
COPY .env.prod .env.prod
COPY .env.test .env.test

ARG VITE_BASE_URL=/
ARG VITE_SERVICE_BASE_URL=/api
ARG VITE_OTHER_SERVICE_BASE_URL={}

ENV VITE_BASE_URL=${VITE_BASE_URL}
ENV VITE_SERVICE_BASE_URL=${VITE_SERVICE_BASE_URL}
ENV VITE_OTHER_SERVICE_BASE_URL=${VITE_OTHER_SERVICE_BASE_URL}

RUN --mount=type=cache,target=/pnpm/store pnpm install --frozen-lockfile --store-dir /pnpm/store
RUN pnpm build

FROM nginx:1.27-alpine

COPY nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=build /app/dist /usr/share/nginx/html

EXPOSE 80
