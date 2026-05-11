import type { NextConfig } from 'next'

// 認証用に **ブラウザから** /api/v1/auth/* を叩く必要がある (cookie がフロント
// ドメインに付くようにするため)。Server Component 側は引き続き API_URL で
// 直接 fetch しているので共存する。
//
// Next.js 16 の rewrites は宛先 URL のポート部 (`:8000`) を route パラメータと
// 誤認するため、`:port` の前にホストを明示しコロンを `\\:` でエスケープした
// 形式を使う必要があった (内部で path-to-regexp が走るため)。
const nextConfig: NextConfig = {
  output: 'standalone',
  async rewrites() {
    const apiUrl = process.env.API_URL || 'http://localhost:8000'
    // ポート部のコロンを path-to-regexp 用にエスケープする
    const safeDest = apiUrl.replace(/:(\d+)/, '\\:$1')
    return [
      {
        source: '/api/v1/:path*',
        destination: `${safeDest}/api/v1/:path*`,
      },
    ]
  },
}

export default nextConfig
