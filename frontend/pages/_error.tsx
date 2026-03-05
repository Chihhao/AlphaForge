import React from 'react'

function Error({ statusCode }: { statusCode?: number }) {
    return (
        <div className="flex flex-col items-center justify-center min-h-[60vh] text-white">
            <h1 className="text-4xl font-bold mb-4">
                {statusCode
                    ? `伺服器錯誤 (${statusCode})`
                    : '客戶端錯誤'}
            </h1>
            <p className="text-zinc-400">
                抱歉，發生了一些問題。請重新整理頁面或稍後再試。
            </p>
        </div>
    )
}

Error.getInitialProps = ({ res, err }: any) => {
    const statusCode = res ? res.statusCode : err ? err.statusCode : 404
    return { statusCode }
}

export default Error
