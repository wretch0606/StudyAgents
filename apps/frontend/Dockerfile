# StudyAgents Frontend — 多阶段构建
# Stage 1: Node — 构建 Vue 应用
# Stage 2: Nginx — 提供静态文件 + 反向代理 /api 和 SSE

FROM node:22-alpine AS builder
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npm run build

FROM nginx:alpine AS runtime
COPY --from=builder /app/dist /usr/share/nginx/html
COPY nginx.conf /etc/nginx/conf.d/default.conf
EXPOSE 80
CMD ["nginx", "-g", "daemon off;"]
