import type { NextConfig } from 'next'

// /api/v1/* の proxy は `src/app/api/v1/[...path]/route.ts` で Route Handler
// として実装している。Next.js の rewrites は宛先のポート部 (`:8000`) を
// route param と誤認するバグがあり脆かったので、より堅牢な Route Handler に
// 切り替えた。
const nextConfig: NextConfig = {
  output: 'standalone',
}

export default nextConfig
