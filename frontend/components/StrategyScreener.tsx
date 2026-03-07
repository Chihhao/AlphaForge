import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import api from '../lib/api';
import EducationalHint from './EducationalHint';

interface ScreenerStock {
    symbol: string;
    name: string;
    price: number;
    change: number;
    bias20: number;
}

interface StrategyResult {
    id: string;
    name: string;
    description: string;
    tag: string;
    stocks: ScreenerStock[];
}

export default function StrategyScreener() {
    const [strategies, setStrategies] = useState<StrategyResult[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchScreener = async () => {
            try {
                const res = await api.get('/market/screener');
                setStrategies(res.data);
            } catch (error) {
                console.error('Failed to fetch screener results', error);
            } finally {
                setLoading(false);
            }
        };
        fetchScreener();
    }, []);

    if (loading) {
        return (
            <div className="w-full flex justify-center items-center py-16 min-h-[300px] border border-white/5 rounded-2xl bg-zinc-900/40">
                <div className="flex flex-col items-center gap-4">
                    <div className="animate-spin h-8 w-8 text-cyan-400 rounded-full border-b-2 border-cyan-400"></div>
                    <span className="text-zinc-500 font-mono text-sm animate-pulse">掃描全市場數據中...</span>
                </div>
            </div>
        );
    }

    return (
        <div className="flex flex-col gap-6 w-full">
            <div className="flex items-center justify-between mb-2">
                <h2 className="text-2xl font-black text-white tracking-widest flex items-center gap-3">
                    <span className="w-1.5 h-6 bg-cyan-400 rounded-full inline-block"></span>
                    今日選股雷達
                </h2>
                <span className="text-sm text-zinc-500 font-mono">
                    自動掃描完成 {new Date().toLocaleTimeString('zh-TW', { hour: '2-digit', minute: '2-digit' })}
                </span>
            </div>

            <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-6 w-full">
                {strategies.map((strategy) => (
                    <div key={strategy.id} className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/10 overflow-hidden shadow-xl hover:border-white/20 transition-all flex flex-col">
                        {/* 策略標題與說明 */}
                        <div className="p-5 border-b border-white/5 bg-white/[0.02]">
                            <div className="flex items-center justify-between mb-2">
                                <div className="flex items-center gap-2">
                                    <h3 className="text-xl font-bold text-white">{strategy.name}</h3>
                                    <div className="scale-90 text-zinc-500 hover:text-cyan-400 transition-colors">
                                        <EducationalHint glossaryId="bias-indicator" />
                                    </div>
                                </div>
                                <span className={`px-2.5 py-1 text-xs font-bold rounded-full ${strategy.tag === '逆勢策略' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'
                                    }`}>
                                    {strategy.tag}
                                </span>
                            </div>
                            <p className="text-zinc-400 text-sm leading-relaxed">{strategy.description}</p>
                        </div>

                        {/* 股票清單 */}
                        <div className="p-2 flex-grow overflow-y-auto max-h-[400px]">
                            {strategy.stocks.length === 0 ? (
                                <div className="p-8 text-center text-zinc-500 font-mono text-sm border-2 border-dashed border-white/5 rounded-xl m-2 bg-black/20">
                                    今日無符合此策略條件之標的
                                </div>
                            ) : (
                                strategy.stocks.map((stock) => {
                                    const isUp = stock.change > 0;
                                    const changeColor = isUp ? 'text-rose-400' : 'text-emerald-400';

                                    return (
                                        <Link key={stock.symbol} href={`/stock/${stock.symbol}`} className="flex items-center justify-between p-3 rounded-xl hover:bg-white/5 transition-colors group cursor-pointer border-l-2 border-transparent hover:border-cyan-400">
                                            <div className="flex flex-col ml-1">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-white font-bold">{stock.name}</span>
                                                    <span className="text-zinc-500 text-xs font-mono">{stock.symbol}</span>
                                                </div>
                                                <div className="flex items-center gap-1 mt-0.5">
                                                    <span className="text-zinc-400 text-xs">20 日乖離率: <span className={stock.bias20 > 0 ? 'text-rose-400/80' : 'text-emerald-400/80'}>{stock.bias20 > 0 ? '+' : ''}{stock.bias20}%</span></span>
                                                </div>
                                            </div>

                                            <div className="flex flex-col items-end">
                                                <span className="text-white font-mono font-bold text-lg">{stock.price}</span>
                                                <span className={`${changeColor} text-sm font-bold font-mono`}>
                                                    {isUp ? '+' : ''}{stock.change}%
                                                </span>
                                            </div>
                                        </Link>
                                    );
                                })
                            )}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
