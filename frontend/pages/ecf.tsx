import React from 'react'
import Head from 'next/head'

const ECFPage = () => {
    return (
        <>
            <Head>
                <title>ECF 分析器 | AlphaForge</title>
                <meta name="description" content="ECF 台灣股市分析器" />
            </Head>
            <div className="w-full h-[calc(100vh-64px)] bg-[#101827]">
                <iframe
                    src="/alphaforge/ecf.html"
                    className="w-full h-full border-none"
                    title="ECF Analyzer"
                />
            </div>
        </>
    )
}

export default ECFPage
