import React, { useState } from 'react';
import Head from 'next/head';
import MarketSummary from '../components/MarketSummary';
import StrategyScreener from '../components/StrategyScreener';
import DailyGlossary from '../components/DailyGlossary';
import SystemConsole from '../components/SystemConsole';

export default function Home() {

  const [isGlossaryOpen, setIsGlossaryOpen] = useState(false);

  return (
    <>
      <Head>
        <title>AlphaForge - 量化儀表板</title>
      </Head>
      <div className="max-w-[1600px] mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-6 pb-12 w-full min-h-screen">

        {/* 控制列或頂部工具列 */}
        <div className="flex justify-between items-center mb-4 sm:mb-6">
          <h1 className="text-2xl sm:text-3xl font-black text-white tracking-widest px-2 opacity-90">儀表板</h1>
          <button
            onClick={() => setIsGlossaryOpen(true)}
            className="flex items-center gap-2 px-4 sm:px-5 py-2.5 bg-indigo-500/10 hover:bg-indigo-500/20 border border-indigo-500/20 text-indigo-300 rounded-xl transition-all shadow-lg active:scale-95 group"
          >
            <span className="text-xl group-hover:scale-110 transition-transform">📚</span>
            <span className="font-bold text-sm sm:text-base hidden sm:inline tracking-wider">今日知識</span>
          </button>
        </div>

        {/* 頂部：大盤溫度計 (Market Pulse) */}
        <section className="mb-6 sm:mb-8">
          <MarketSummary />
        </section>

        {/* 單欄佈局：全寬度的選股雷達 */}
        <section className="w-full">
          <StrategyScreener />
        </section>
      </div>

      {/* 隱藏式知識卡抽屜 (Drawer) */}
      <DailyGlossary isOpen={isGlossaryOpen} onClose={() => setIsGlossaryOpen(false)} />

      {/* 系統狀態看板 */}
      <SystemConsole />
    </>
  )
}
