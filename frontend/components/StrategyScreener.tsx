import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import api from '../lib/api';
import { todayLabel } from '../lib/formatters';
import EducationalHint from './EducationalHint';

interface ScreenerStock {
    symbol: string;
    name: string;
    price: number;
    change: number;
    bias20: number;
    yield_rate?: number;
    roe?: number;
    pb?: number;
    volume_avg_5d?: number;
}

interface StrategyResult {
    id: string;
    name: string;
    description: string;
    tag: string;
    stocks: ScreenerStock[];
    data_date?: string;
    is_live: boolean;
}

export default function StrategyScreener() {
    const [strategies, setStrategies] = useState<StrategyResult[]>([]);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        const fetchScreener = async (showLoading = true) => {
            if (showLoading) setLoading(true);
            try {
                const res = await api.get('/market/screener');
                setStrategies(res.data);
            } catch (error) {
                console.error('Failed to fetch screener results', error);
            } finally {
                if (showLoading) setLoading(false);
            }
        };

        // 首次加載
        fetchScreener(true);

        // 盤中自動輪詢邏輯 (每 60 秒一次)
        const intervalId = setInterval(() => {
            const now = new Date();
            const day = now.getDay(); // 0 是週日, 6 是週六
            const hours = now.getHours();
            const minutes = now.getMinutes();
            const timeValue = hours * 100 + minutes;

            // 判斷是否為週一至週五的交易時段 (09:00 - 14:30)
            const isTradingDay = day >= 1 && day <= 5;
            const isTradingHour = timeValue >= 900 && timeValue <= 1430;

            if (isTradingDay && isTradingHour) {
                fetchScreener(false); // 背景刷新，不顯示 loading 動畫
            }
        }, 60000);

        return () => clearInterval(intervalId);
    }, []);

    return (
        <div className="flex flex-col gap-6 w-full">

            {loading ? (
                <div className="w-full flex justify-center items-center py-16 min-h-[300px] border border-white/5 rounded-2xl bg-zinc-900/40">
                    <div className="flex flex-col items-center gap-4">
                        <div className="animate-spin h-8 w-8 text-cyan-400 rounded-full border-b-2 border-cyan-400"></div>
                        <span className="text-zinc-500 font-mono text-sm animate-pulse">選股雷達掃描中...</span>
                    </div>
                </div>
            ) : (
                <div className="grid grid-cols-1 lg:grid-cols-2 2xl:grid-cols-3 gap-4 w-full">
                    {strategies.map((strategy) => (
                        <div key={strategy.id} className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/10 overflow-hidden shadow-xl hover:border-white/20 transition-all flex flex-col">
                            {/* 策略標題與說明 */}
                            <div className="p-5 border-b border-white/5 bg-white/[0.02]">
                                <div className="flex items-start justify-between mb-2">
                                    <div className="flex flex-col">
                                        <div className="flex items-center gap-2">
                                            <h3 className="text-xl font-bold text-white whitespace-nowrap">
                                                {strategy.name} ({strategy.stocks.length}檔)
                                            </h3>
                                            <div className="scale-90 text-zinc-500 hover:text-cyan-400 transition-colors">
                                                <EducationalHint glossaryId={strategy.id === 'af_choice' ? 'af-choice-strategy' : 'bias-indicator'} />
                                            </div>
                                        </div>
                                        {strategy.data_date && (
                                            <span className="text-[10px] font-medium text-zinc-400 tracking-wide flex items-center gap-1.5 mt-0.5">
                                                已於 {strategy.data_date} 盤後刷新
                                            </span>
                                        )}
                                    </div>
                                    <span className={`px-2.5 py-1 text-xs font-bold rounded-full ${strategy.tag === '逆勢策略' ? 'bg-rose-500/20 text-rose-400' :
                                        strategy.tag === '價值成長股' ? 'bg-cyan-500/20 text-cyan-400' :
                                            'bg-emerald-500/20 text-emerald-400'
                                        }`}>
                                        {strategy.tag}
                                    </span>
                                </div>
                                <p className="text-zinc-400 text-sm leading-relaxed min-h-[40px]">{strategy.description}</p>
                            </div>

                            {/* 股票清單 */}
                            <div className="p-2 flex-grow overflow-y-auto max-h-[400px]">
                                {strategy.stocks.length === 0 ? (
                                    <div className="p-8 text-center text-zinc-500 font-mono text-sm border-2 border-dashed border-white/5 rounded-xl m-2 bg-black/20">
                                        此參數條件下 {todayLabel()} 無符合標的
                                    </div>
                                ) : (
                                    strategy.stocks.map((stock, index) => {
                                        const isUp = stock.change > 0;
                                        const changeColor = isUp ? 'text-rose-400' : (stock.change < 0 ? 'text-emerald-400' : 'text-zinc-400');
                                        const isFundamental = strategy.id === 'af_choice';

                                        return (
                                            <React.Fragment key={stock.symbol}>
                                                <Link
                                                    href={`/stock/${stock.symbol}`}
                                                    className="flex items-center gap-2 py-2.5 px-2 rounded-lg hover:bg-white/5 transition-colors group cursor-pointer border-b border-zinc-800/40 last:border-b-0"
                                                >
                                                    <span className={`font-mono font-bold text-xs w-4 shrink-0 text-center ${index < 3 ? 'text-cyan-400' : 'text-zinc-600'}`}>{index + 1}</span>
                                                    <div className="flex flex-col flex-1 min-w-0">
                                                        <div className="flex items-center gap-2">
                                                            <span className="text-sm font-semibold text-zinc-100">{stock.name}</span>
                                                            <span className="text-xs text-zinc-500 font-mono">{stock.symbol}</span>
                                                        </div>
                                                        <div className="flex items-center gap-1 mt-0.5">
                                                            {isFundamental ? (
                                                                <div className="flex gap-2">
                                                                    <span className="text-zinc-400 text-xs text-nowrap">
                                                                        殖利率: <span className="text-rose-400/90">
                                                                            {(stock.yield_rate ?? 0) > 50 ? ((stock.yield_rate ?? 0) / 100).toFixed(1) : (stock.yield_rate ?? 0).toFixed(1)}%
                                                                        </span>
                                                                    </span>
                                                                    <span className="text-zinc-400 text-xs text-nowrap">
                                                                        ROE: <span className="text-cyan-400/90">{(stock.roe ?? 0).toFixed(1)}%</span>
                                                                    </span>
                                                                    {stock.pb !== undefined && (
                                                                        <span className="text-zinc-400 text-xs text-nowrap">
                                                                            PB: <span className="text-amber-400/90">{stock.pb.toFixed(1)}x</span>
                                                                        </span>
                                                                    )}
                                                                </div>
                                                            ) : (
                                                                <span className="text-zinc-400 text-xs">20 日乖離率: <span className={stock.bias20 > 0 ? 'text-rose-400/80' : 'text-emerald-400/80'}>{stock.bias20 > 0 ? '+' : ''}{stock.bias20}%</span></span>
                                                            )}
                                                        </div>
                                                    </div>

                                                    <div className="flex flex-col items-end">
                                                        <div className="flex items-center">
                                                            {stock.change > 0 && <span className="text-rose-400 text-[10px] mr-1">▲</span>}
                                                            {stock.change < 0 && <span className="text-emerald-400 text-[10px] mr-1">▼</span>}
                                                            <span className={`${changeColor} font-mono font-bold text-sm`}>
                                                                {stock.price === 0 ? '---' :
                                                                    stock.price < 100 ? stock.price.toFixed(2) :
                                                                        stock.price < 500 ? stock.price.toFixed(1) :
                                                                            Math.round(stock.price).toString()
                                                                }
                                                            </span>
                                                        </div>
                                                        <span className={`${changeColor} text-xs font-bold font-mono`}>
                                                            {stock.change === 0 ? '0.00' : (stock.change > 0 ? '+' : '') + stock.change.toFixed(2)}%
                                                        </span>
                                                    </div>
                                                </Link>
                                            </React.Fragment>
                                        );
                                    })
                                )}
                            </div>
                        </div>
                    ))}
                </div>
            )}
        </div>
    );
}
