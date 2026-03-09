import React, { useRef, useEffect } from 'react'
import Head from 'next/head'
import ECFHeader from '../components/ECFHeader'

const ECFPage = () => {
    const iframeRef = useRef<HTMLIFrameElement>(null);

    const injectStyles = () => {
        if (!iframeRef.current) return;
        try {
            const doc = iframeRef.current.contentDocument || iframeRef.current.contentWindow?.document;
            if (doc) {
                const style = doc.createElement('style');
                style.textContent = `
                    /* 1. 隱藏 ECF.html 原本的標題 */
                    .header { display: none !important; }
                    
                    /* 2. 移除上下填充，讓排版更緊湊 */
                    .container { 
                        padding-top: 0 !important; 
                        max-width: 100% !important; 
                        margin: 0 !important;
                        background: transparent !important;
                    }
                    
                    /* 3. 背景與字體統一 AlphaForge 風格 */
                    body { 
                        background: transparent !important; 
                        font-family: 'IBM Plex Sans', 'Noto Sans TC', sans-serif !important;
                        color: #f8fafc !important; /* text-slate-50 */
                    }
                    
                    /* 4. 自定義捲軸 */
                    ::-webkit-scrollbar { width: 8px; height: 8px; }
                    ::-webkit-scrollbar-track { background: #030712; }
                    ::-webkit-scrollbar-thumb { 
                        background: #1e293b; 
                        border-radius: 4px; 
                        border: 2px solid #030712;
                    }
                    ::-webkit-scrollbar-thumb:hover { background: #334155; }
                `;
                doc.head.appendChild(style);
            }
        } catch (e) {
            console.error('Failed to inject ECF styles:', e);
        }
    };

    return (
        <>
            <Head>
                <title>ECF 專家分析 | AlphaForge</title>
                <meta name="description" content="AlphaForge 整合型 ECF 專家分析系統" />
            </Head>

            <div className="flex flex-col min-h-screen bg-black">
                {/* 重新設計的標題組件 */}
                <ECFHeader />

                {/* ECF 內容 iframe */}
                <div className="flex-1 w-full bg-[#030712] relative">
                    <iframe
                        ref={iframeRef}
                        src="/alphaforge/ecf.html"
                        className="w-full h-full border-none"
                        title="ECF Analyzer"
                        onLoad={injectStyles}
                        style={{ minHeight: '800px' }}
                    />
                </div>
            </div>
        </>
    )
}

export default ECFPage

