import '../styles/globals.css'
import 'katex/dist/katex.min.css'
import type { AppProps } from 'next/app'
import dynamic from 'next/dynamic'

// 徹底停用 Layout 的 SSR，避免手機模擬器與 React Hydration 發生衝突
const DynamicLayout = dynamic(() => import('../components/Layout'), {
  ssr: false,
  loading: () => <div className="min-h-screen bg-[#101827]" />
})

export default function App({ Component, pageProps }: AppProps) {
  return (
    <DynamicLayout>
      <Component {...pageProps} />
    </DynamicLayout>
  )
}
