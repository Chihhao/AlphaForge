import React, { useEffect } from 'react';

interface DailyGlossaryProps {
    isOpen: boolean;
    onClose: () => void;
}

export default function DailyGlossary({ isOpen, onClose }: DailyGlossaryProps) {
    // 當 Drawer 打開時禁止背景滾動
    useEffect(() => {
        if (isOpen) {
            document.body.style.overflow = 'hidden';
        } else {
            document.body.style.overflow = '';
        }
        return () => {
            document.body.style.overflow = '';
        };
    }, [isOpen]);

    return (
        <>
            {/* 背景遮罩 */}
            <div
                className={`fixed inset-0 bg-black/60 backdrop-blur-sm z-40 transition-opacity duration-300 ${isOpen ? 'opacity-100' : 'opacity-0 pointer-events-none'}`}
                onClick={onClose}
            />

            {/* 側邊抽屜 */}
            <div
                className={`fixed top-0 right-0 h-full w-full sm:w-[400px] md:w-[450px] bg-[#0c0c0e] border-l border-white/5 z-50 transform transition-transform duration-300 ease-in-out shadow-2xl flex flex-col ${isOpen ? 'translate-x-0' : 'translate-x-full'}`}
            >
                {/* 抽屜頂部 */}
                <div className="flex items-center justify-between p-6 border-b border-white/5 bg-zinc-900/30">
                    <div className="flex items-center gap-3">
                        <div className="bg-indigo-500/20 p-2 rounded-xl border border-indigo-500/20 shadow-inner">
                            <span className="text-2xl block leading-none">📚</span>
                        </div>
                        <h2 className="text-xl font-black text-white tracking-widest">每日知識卡</h2>
                    </div>
                    <button
                        onClick={onClose}
                        className="w-10 h-10 flex items-center justify-center rounded-full bg-white/5 hover:bg-white/10 border border-white/5 text-zinc-400 hover:text-white transition-all active:scale-95"
                    >
                        <svg className="w-5 h-5" fill="none" stroke="currentColor" viewBox="0 0 24 24"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M6 18L18 6M6 6l12 12" /></svg>
                    </button>
                </div>

                {/* 抽屜內容 */}
                <div className="flex-1 overflow-y-auto p-6 sm:p-8 scrollbar-hide relative bg-gradient-to-b from-[#0c0c0e] to-[#121218]">
                    {/* 背景漸層裝飾 */}
                    <div className="absolute top-10 right-0 w-64 h-64 bg-indigo-600/10 blur-[100px] rounded-full pointer-events-none" />
                    <div className="absolute bottom-10 left-0 w-64 h-64 bg-purple-600/10 blur-[100px] rounded-full pointer-events-none" />

                    <div className="relative z-10 w-full">
                        <h3 className="text-3xl font-black bg-clip-text text-transparent bg-gradient-to-br from-white via-indigo-100 to-indigo-400 mb-8 leading-tight">
                            支撐與壓力 <br />
                            <span className="text-lg text-indigo-300/70 font-mono tracking-widest uppercase block mt-2">Support and Resistance</span>
                        </h3>

                        <div className="space-y-6 text-zinc-300 leading-relaxed text-base md:text-lg mb-10">
                            <p className="bg-white/[0.02] p-4 rounded-xl border border-white/5">
                                市場心理學的核心。當股價下跌到某個價位，因為「套牢想攤平」或「空手想上車」的買盤湧現，形成
                                <strong className="text-emerald-400 font-bold bg-emerald-400/10 px-2 py-0.5 rounded mx-1">支撐區</strong>。
                            </p>
                            <p className="bg-white/[0.02] p-4 rounded-xl border border-white/5">
                                反之，當股價上漲到某個價位，因為「獲利了結」或「套牢解套」的賣壓湧現，形成
                                <strong className="text-rose-400 font-bold bg-rose-400/10 px-2 py-0.5 rounded mx-1">壓力區</strong>。
                            </p>
                        </div>

                        <div className="bg-gradient-to-br from-zinc-900/80 to-black/80 rounded-2xl p-6 border border-white/5 relative overflow-hidden backdrop-blur-md shadow-xl">
                            <div className="absolute -top-6 -right-6 w-32 h-32 bg-indigo-500/20 rounded-full blur-[30px] pointer-events-none"></div>
                            <div className="relative z-10">
                                <span className="text-indigo-400 font-black flex items-center gap-2 mb-4 text-lg">
                                    <span className="text-xl">💡</span> 量化視角
                                </span>
                                <p className="text-zinc-400 text-sm md:text-base leading-relaxed">
                                    在設計策略時，我們常利用過去 N 天的「成交量密集區」作為數學上的壓力或支撐線，而非單憑肉眼感覺。這讓停損與停利的設定有了非常客觀的基準點，排除人為的僥倖心態。
                                </p>
                            </div>
                        </div>

                        <div className="mt-12 flex justify-center opacity-30">
                            <div className="h-1 w-12 bg-zinc-600 rounded-full"></div>
                        </div>
                    </div>
                </div>
            </div>
        </>
    );
}
