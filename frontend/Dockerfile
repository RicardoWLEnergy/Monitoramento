# Etapa 1: compila o Angular (o Node só existe nesta etapa)
FROM node:22-alpine AS compilar
WORKDIR /app
COPY package.json package-lock.json ./
RUN npm ci
COPY . .
RUN npx ng build --configuration production

# Etapa 2: a imagem final tem só o Caddy + as telas prontas
FROM caddy:2-alpine
COPY --from=compilar /app/dist/frontend/browser /srv
