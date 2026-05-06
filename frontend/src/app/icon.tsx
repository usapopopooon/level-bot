import { ImageResponse } from 'next/og'

export const size = { width: 32, height: 32 }
export const contentType = 'image/png'

// 動的に生成される favicon。画像ファイルを置かなくても /icon.png として配信され、
// ブラウザが自動取得する /favicon.ico の代わりになる (Next.js が自動配線)。
export default function Icon() {
  return new ImageResponse(
    (
      <div
        style={{
          fontSize: 24,
          background: '#5865F2',
          color: 'white',
          width: '100%',
          height: '100%',
          display: 'flex',
          alignItems: 'center',
          justifyContent: 'center',
          borderRadius: 6,
        }}
      >
        📊
      </div>
    ),
    size,
  )
}
