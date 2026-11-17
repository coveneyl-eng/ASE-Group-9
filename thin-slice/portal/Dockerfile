# Build the React + TypeScript portal, serve it from the NGINX gateway image.
FROM node:22-alpine AS build
WORKDIR /portal
COPY package*.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:1.27-alpine
COPY --from=build /portal/dist /usr/share/nginx/html
