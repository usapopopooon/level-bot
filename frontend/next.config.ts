import type { NextConfig } from 'next'

// 全ページが Server Component で API_URL を直接 fetch する設計のため、
// /api/v1/* をフロント経由で外部に rewrite する必要はない。
// Next.js 16 の rewrites は宛先 URL のポート部 (`:8000`) をパラメータとして
// 解釈してしまい "Invalid rewrite found" でビルドが落ちるため、定義しない。
const nextConfig: NextConfig = {
  output: 'standalone',
}

export default nextConfig
