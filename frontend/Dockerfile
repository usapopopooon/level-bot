# =============================================================================
# Next.js standalone build (multi-stage)
# =============================================================================
# Railway 上ではこのサービスの "Root Directory" を `frontend/` に設定し、
# build context = frontend/ となる前提。frontend/railway.toml は dockerfilePath を
# "Dockerfile" (相対) として参照する。
# =============================================================================

# --- deps stage: 依存関係キャッシュ層 ---
FROM node:24-alpine AS deps
WORKDIR /app
COPY package.json package-lock.json* ./
RUN npm ci || npm install


# --- builder stage: Next.js のビルド ---
FROM node:24-alpine AS builder
WORKDIR /app
COPY --from=deps /app/node_modules ./node_modules
COPY . .

# API_URL は build 時に rewrites と server component の fetch 先に焼き込まれる。
# Railway では service variable で本番 API URL を渡す。
ARG API_URL=http://localhost:8000
ENV API_URL=$API_URL
ENV NEXT_TELEMETRY_DISABLED=1

RUN npm run build


# --- runner stage: 実行に最低限のものだけコピー ---
FROM node:24-alpine AS runner
WORKDIR /app
ENV NODE_ENV=production
ENV NEXT_TELEMETRY_DISABLED=1
ENV HOSTNAME=0.0.0.0
ENV PORT=3000

# Next.js は --output=standalone で
#   .next/standalone/         ← server.js + 最小 node_modules
#   .next/static/             ← 静的アセット
#   public/                   ← 静的ファイル (任意)
# を生成する。standalone 配下に server.js があるのでそこへ static / public を寄せる。
COPY --from=builder /app/.next/standalone ./
COPY --from=builder /app/.next/static ./.next/static
COPY --from=builder /app/public ./public

EXPOSE 3000
CMD ["node", "server.js"]
