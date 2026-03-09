import React from 'react'
import Head from 'next/head'

const StrategyPage = () => {
    // MDI Icon Paths
    const icons = {
        strategy: "M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z",
        rocket: "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M11,16.5L6.5,12L7.91,10.59L11,13.67L16.09,8.58L17.5,10L11,16.5Z",
        chart: "M19,3H5C3.89,3 3,3.9 3,5V19C3,20.1 3.89,21 5,21H19C20.1,21 21,20.1 21,19V5C21,3.9 20.1,3 19,3M9,17H7V10H9V17M13,17H11V7H13V17M17,17H15V13H17V17Z",
        settings: "M12,15.5A3.5,3.5 0 0,1 8.5,12A3.5,3.5 0 0,1 12,8.5A3.5,3.5 0 0,1 15.5,12A3.5,3.5 0 0,1 12,15.5M19.43,12.97C19.47,12.65 19.5,12.33 19.5,12C19.5,11.67 19.47,11.35 19.43,11.03L21.54,9.37C21.73,9.22 21.78,8.95 21.66,8.73L19.66,5.27C19.54,5.05 19.27,4.97 19.05,5.05L16.56,6.05C16.04,5.66 15.5,5.32 14.87,5.07L14.5,2.42C14.46,2.18 14.25,2 14,2H10C9.75,2 9.54,2.18 9.5,2.42L9.13,5.07C8.5,5.32 7.96,5.66 7.44,6.05L4.95,5.05C4.73,4.97 4.46,5.05 4.34,5.27L2.34,8.73C2.21,8.95 2.27,9.22 2.46,9.37L4.57,11.03C4.53,11.35 4.5,11.67 4.5,12C4.5,12.33 4.53,12.65 4.57,12.97L2.46,14.63C2.27,14.78 2.21,15.05 2.34,15.27L4.34,18.73C4.46,18.95 4.73,19.03 4.95,18.95L7.44,17.95C7.96,18.34 8.5,18.68 9.13,18.93L9.5,21.58C9.54,21.82 9.75,22 10,22H14C14.25,22 14.46,21.82 14.5,21.58L14.87,18.93C15.5,18.68 16.04,18.34 16.56,17.95L19.05,18.95C19.27,19.03 19.54,18.95 19.66,18.73L21.66,15.27C21.78,15.05 21.73,14.78 21.54,14.63L19.43,12.97Z",
        alert: "M13,14H11V10H13M13,18H11V16H13M1,21H23L12,2L1,21Z"
    }

    const SVGIcon = ({ path, className = "w-6 h-6" }: { path: string, className?: string }) => (
        <svg viewBox="0 0 24 24" className={`fill-current ${className}`}>
            <path d={path} />
        </svg>
    )

    return (
        <>
            <Head>
                <title>策略開發 | AlphaForge</title>
            </Head>

            <div className="min-h-[calc(100vh-64px)] p-4 sm:p-8 flex flex-col gap-6 max-w-7xl mx-auto">
                {/* Enhanced Header Section */}
                <div className="relative overflow-hidden bg-zinc-900/30 border border-zinc-800/50 rounded-3xl p-6 sm:p-8 mb-2 group">
                    {/* Background Decorative Gradient */}
                    <div className="absolute top-0 right-0 w-64 h-64 bg-emerald-500/5 rounded-full blur-3xl -mr-32 -mt-32 transition-colors group-hover:bg-emerald-500/10" />

                    <div className="relative flex flex-col md:flex-row md:items-center justify-between gap-6">
                        <div className="flex flex-col gap-1">
                            <div className="flex items-center gap-3">
                                <div className="p-2 bg-emerald-500/10 rounded-xl border border-emerald-500/20">
                                    <SVGIcon path={icons.strategy} className="w-6 h-6 text-emerald-400" />
                                </div>
                                <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-white flex items-center gap-2">
                                    策略<span className="bg-gradient-to-r from-emerald-400 to-teal-500 bg-clip-text text-transparent">開發</span>
                                </h1>
                            </div>
                            <p className="text-zinc-400 text-sm sm:text-base font-medium mt-1 pl-1 border-l-2 border-emerald-500/30">
                                系統化量化研究與回測 · <span className="text-zinc-600 font-mono text-xs uppercase tracking-tighter">Quantitative Lab</span>
                            </p>
                        </div>

                        <div className="flex items-center self-start md:self-center">
                            <div className="group/badge relative px-4 py-2 bg-zinc-950 border border-zinc-800 rounded-2xl flex items-center gap-3 shadow-xl overflow-hidden">
                                {/* Badge Shimmier */}
                                <div className="absolute inset-0 bg-gradient-to-r from-transparent via-emerald-500/5 to-transparent -translate-x-full animate-[shimmer_2s_infinite] pointer-events-none" />

                                <span className="relative flex h-2 w-2">
                                    <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-75"></span>
                                    <span className="relative inline-flex rounded-full h-2 w-2 bg-emerald-500"></span>
                                </span>
                                <span className="text-zinc-300 text-xs font-bold tracking-widest uppercase flex items-center gap-2">
                                    深度開發中 <span className="text-zinc-600">|</span> <span className="text-emerald-500/80">Coming Soon</span>
                                </span>
                            </div>
                        </div>
                    </div>
                </div>

                {/* Main Content Skeleton */}
                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">

                    {/* Left Panel: Strategy Library Mockup */}
                    <div className="lg:col-span-3 flex flex-col gap-4">
                        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5">
                            <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest mb-4 flex items-center gap-2">
                                <SVGIcon path={icons.rocket} className="w-4 h-4 text-emerald-400" />
                                策略模板
                            </h3>
                            <div className="space-y-3">
                                {[1, 2, 3].map(i => (
                                    <div key={i} className="h-12 bg-zinc-800/50 rounded-xl border border-zinc-700/30 animate-pulse" />
                                ))}
                            </div>
                        </div>

                        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-5 flex-grow">
                            <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest mb-4">我的方案</h3>
                            <div className="flex flex-col items-center justify-center h-32 border-2 border-dashed border-zinc-800 rounded-xl">
                                <SVGIcon path={icons.settings} className="w-8 h-8 text-zinc-700 mb-2" />
                                <span className="text-zinc-600 text-xs">尚無存檔</span>
                            </div>
                        </div>
                    </div>

                    {/* Middle Panel: Chart & Visualizer Mockup */}
                    <div className="lg:col-span-9 flex flex-col gap-6">

                        {/* Visualization Area */}
                        <div className="aspect-video lg:aspect-auto lg:h-[450px] bg-zinc-900/80 border border-zinc-800 rounded-3xl relative overflow-hidden group">
                            {/* Animated Background Overlay */}
                            <div className="absolute inset-0 bg-gradient-to-br from-emerald-500/5 to-transparent pointer-events-none" />

                            {/* Construction Message */}
                            <div className="absolute inset-0 flex flex-col items-center justify-center p-8 text-center mt-[-20px]">
                                <div className="mb-6 p-6 bg-zinc-950 rounded-full border border-emerald-500/20 shadow-[0_0_50px_-12px_rgba(16,185,129,0.3)]">
                                    <SVGIcon path={icons.strategy} className="w-16 h-16 text-emerald-500" />
                                </div>
                                <h2 className="text-2xl sm:text-3xl font-bold text-white mb-2">AlphaForge 工作區升級中</h2>
                                <p className="text-zinc-500 max-w-md text-sm sm:text-base leading-relaxed">
                                    我們正在打造一個高效率、響應式的策略回測引擎。
                                    未來您可以在此處自定義交易邏輯，並即時查看視覺化績效報告。
                                </p>

                                <div className="mt-8 grid grid-cols-2 sm:grid-cols-4 gap-4 w-full max-w-xl">
                                    {[
                                        { label: '多標的回測', icon: icons.chart },
                                        { label: '視覺化條件', icon: icons.settings },
                                        { label: '模擬組合', icon: icons.rocket },
                                        { label: '風險分析', icon: icons.alert }
                                    ].map((feat, idx) => (
                                        <div key={idx} className="flex flex-col items-center gap-2 p-3 bg-zinc-800/30 rounded-2xl border border-zinc-700/20">
                                            <SVGIcon path={feat.icon} className="w-5 h-5 text-emerald-400/60" />
                                            <span className="text-[10px] text-zinc-500 font-bold uppercase">{feat.label}</span>
                                        </div>
                                    ))}
                                </div>
                            </div>
                        </div>

                        {/* Parameter Controls Skeleton */}
                        <div className="bg-zinc-900/50 border border-zinc-800 rounded-2xl p-6">
                            <div className="flex justify-between items-center mb-6">
                                <h3 className="text-zinc-400 text-xs font-bold uppercase tracking-widest">策略參數調整 (Coming Soon)</h3>
                                <div className="h-4 w-20 bg-emerald-500/20 rounded animate-pulse" />
                            </div>
                            <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
                                {[1, 2, 3].map(i => (
                                    <div key={i} className="space-y-3">
                                        <div className="h-3 w-24 bg-zinc-800 rounded" />
                                        <div className="h-2 w-full bg-zinc-800 rounded-full" />
                                    </div>
                                ))}
                            </div>
                        </div>
                    </div>

                </div>

            </div>

            <style jsx>{`
                @keyframes pulse-soft {
                    0%, 100% { opacity: 1; }
                    50% { opacity: 0.7; }
                }
                @keyframes shimmer {
                    100% { transform: translateX(100%); }
                }
                .animate-pulse-soft {
                    animation: pulse-soft 3s cubic-bezier(0.4, 0, 0.6, 1) infinite;
                }
            `}</style>
        </>
    )
}

export default StrategyPage
