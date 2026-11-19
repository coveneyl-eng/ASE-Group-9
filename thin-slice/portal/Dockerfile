# Build the React + TypeScript portal, serve it from the NGINX gateway image.
FROM node:22-alpine AS build
WORKDIR /portal
COPY package*.json ./
# Generous retries/timeouts so slow Wi-Fi doesn't kill the build; the cache mount keeps finished downloads between retries
RUN --mount=type=cache,target=/root/.npm \
    npm ci --no-audit --no-fund --fetch-retries=10 --fetch-retry-mintimeout=20000 --fetch-retry-maxtimeout=180000
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /portal/dist /usr/share/nginx/html
