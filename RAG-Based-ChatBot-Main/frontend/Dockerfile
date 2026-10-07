# ============================================
# DocuChat Frontend - Multi-Stage Dockerfile
# ============================================

# Stage 1: Build React static assets
FROM node:20-alpine AS builder

WORKDIR /app

COPY frontend/package.json ./
RUN npm install

COPY frontend/ ./
RUN npm run build

# Stage 2: Production Nginx Server
FROM nginx:alpine

# Remove default nginx html
RUN rm -rf /usr/share/nginx/html/*

# Copy built bundle
COPY --from=builder /app/build /usr/share/nginx/html

# Custom nginx config for SPA routing
RUN printf 'server {\n\
    listen 3000;\n\
    location / {\n\
        root /usr/share/nginx/html;\n\
        index index.html index.htm;\n\
        try_files $uri $uri/ /index.html;\n\
    }\n\
}\n' > /etc/nginx/conf.d/default.conf

EXPOSE 3000

CMD ["nginx", "-g", "daemon off;"]
