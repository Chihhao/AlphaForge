import { Html, Head, Main, NextScript } from 'next/document'

export default function Document() {
  return (
    <Html lang="zh-TW" suppressHydrationWarning>
      <Head>
        <meta charSet="utf-8" />
        <script
          dangerouslySetInnerHTML={{
            __html: `
                        (function() {
                          const patch = () => {
                            try {
                              if (typeof window !== 'undefined' && window.navigator) {
                                const nav = window.navigator;
                                if (nav.userAgentData && !nav.userAgentData.brands) {
                                  try {
                                    Object.defineProperty(nav.userAgentData, 'brands', {
                                      value: [], writable: true, configurable: true
                                    });
                                  } catch (e) {
                                    // 強制覆蓋被破壞的物件
                                    const mock = { brands: [], mobile: false, platform: 'Unknown', getHighEntropyValues: () => Promise.resolve({}) };
                                    Object.defineProperty(nav, 'userAgentData', { value: mock, configurable: true });
                                  }
                                }
                              }
                            } catch (e) {}
                          };
                          patch();
                          window.addEventListener('DOMContentLoaded', patch);
                          window.addEventListener('load', patch);
                        })();
                    `,
          }}
        />
        <title>AlphaForge_ | 專業級台股策略鍛造平台</title>
        <meta name="description" content="AlphaForge 為投資者提供最強大的台股策略研發與回測工具，助您鍛造出高勝率的投資組合。" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <link rel="icon" type="image/svg+xml" href="/alphaforge/favicon.svg?v=3" />
        <link rel="shortcut icon" href="/alphaforge/favicon.svg?v=3" />
        <link rel="apple-touch-icon" href="/alphaforge/apple-touch-icon.png?v=3" />
        <meta name="mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-capable" content="yes" />
        <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
        <meta name="apple-mobile-web-app-title" content="AlphaForge" />
      </Head>
      <body suppressHydrationWarning>
        <Main />
        <NextScript />
      </body>
    </Html>
  )
}
