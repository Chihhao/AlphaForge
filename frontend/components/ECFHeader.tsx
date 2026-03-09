import React from 'react';

const ECFHeader: React.FC = () => {
    return (
        <header className="relative py-5 px-6 overflow-hidden border-b border-zinc-900/50 bg-[#09090b]">
            {/* Background elements for depth */}
            <div className="absolute top-0 left-1/4 w-[500px] h-[300px] bg-emerald-500/5 blur-[120px] rounded-full pointer-events-none" />
            <div className="absolute bottom-0 right-1/4 w-[500px] h-[300px] bg-blue-500/5 blur-[120px] rounded-full pointer-events-none" />

            <div className="max-w-7xl mx-auto relative z-10 flex flex-col items-center text-center">
                {/* Main Title */}
                <h1 className="text-3xl md:text-4xl font-black tracking-tighter mb-2 flex flex-wrap justify-center items-center gap-x-4">
                    <span className="bg-gradient-to-b from-white to-zinc-400 bg-clip-text text-transparent">
                        ECF 台股分析系統
                    </span>
                    <span className="text-emerald-500 font-mono text-lg border border-emerald-500/30 px-3 py-0.5 rounded-lg bg-emerald-500/5 shadow-[0_0_20px_rgba(16,185,129,0.1)]">
                        V60
                    </span>
                </h1>

                {/* Notice Text (Compact) */}
                <p className="text-[10px] md:text-xs text-zinc-500 font-medium tracking-wide">
                    <span className="text-red-500 mr-1 animate-pulse">●</span>
                    證交所 / 櫃買中心資料約於每日 <span className="text-zinc-300 font-bold font-mono">18:00</span> 更新，當日資料請於盤後查詢
                </p>
            </div>
        </header>
    );
};

export default ECFHeader;
