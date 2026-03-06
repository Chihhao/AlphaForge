import React, { useState, useEffect } from 'react';
import api from '../lib/api';
import EducationalHint from './EducationalHint';
import { formatPrice } from '../lib/formatters';

interface MarketSummaryData {
    taiex_price: number;
    taiex_change: number;
    taiex_change_percent: number;
    taiex_volume: number;
    avg_volume_5d: number;
    volume_ratio: number;
    advances: number;
    declines: number;
    unchanged: number;
    limit_up: number;
    limit_down: number;
    advance_decline_ratio: number;
    market_sentiment: string;
    volume_status: string;
    data_date: string;
}

/**
 * 大盤指數概況組件（單卡片版）
 *
 * 在一張卡片內整合加權指數、成交量、多空比三大資訊
 */
export default function MarketSummary() {
    const [data, setData] = useState<MarketSummaryData | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState(false);

    useEffect(() => {
        const fetchSummary = async () => {
            try {
                const res = await api.get('/market/summary');
                setData(res.data);
            } catch (err) {
                console.error('Failed to fetch market summary', err);
                setError(true);
            } finally {
                setLoading(false);
            }
        };
        fetchSummary();
    }, []);

    if (loading) {
        return (
            <div className="bg-zinc-900/60 backdrop-blur-md rounded-2xl border border-white/5 p-6 mb-6 animate-pulse">
                <div className="h-8 bg-zinc-700/50 rounded w-48 mb-3" />
                <div className="h-5 bg-zinc-700/50 rounded w-32" />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/5 p-5 mb-6 text-center">
                <p className="text-zinc-500 text-sm">市場資料載入失敗，請稍後重試</p>
            </div>
        );
    }

    const isUp = data.taiex_change >= 0;
    // 台股習慣：紅漲綠跌
    const changeColor = isUp ? 'text-rose-500' : 'text-emerald-400';
    const changeArrow = isUp ? '▲' : '▼';

    return (
        <div className={`relative overflow-hidden bg-gradient-to-br ${isUp ? 'from-rose-900/20 to-zinc-900/80' : 'from-emerald-900/30 to-zinc-900/80'} backdrop-blur-md rounded-2xl border border-white/10 p-4 sm:p-5 mb-5 shadow-xl`}>
            {/* 背景裝飾 */}
            <div className="absolute -right-10 -top-10 w-40 h-40 rounded-full bg-white/[0.015]" />

            {/* 主要內容區 */}
            <div className="relative z-10 flex flex-col text-white">
                {/* 標題與小統計 */}
                <div className="flex items-center justify-between mb-1.5 sm:mb-2.5">
                    <div className="flex items-center gap-2">
                        <span className="text-xl sm:text-2xl font-black tracking-widest uppercase text-white">加權指數</span>
                        <div className="inline-flex text-zinc-400 opacity-50 hover:opacity-100 transition-opacity">
                            <EducationalHint glossaryId="taiex" />
                        </div>
                    </div>

                    {/* 漲跌家數小標籤 */}
                    <div className="flex items-center gap-x-4">
                        <div className="flex items-baseline gap-1.5">
                            <span className="text-rose-500 font-bold text-sm sm:text-base">漲</span>
                            <span className="text-rose-400 font-black font-mono text-lg sm:text-xl">{data.advances}</span>
                        </div>
                        <div className="flex items-baseline gap-1.5">
                            <span className="text-emerald-500 font-bold text-sm sm:text-base">跌</span>
                            <span className="text-emerald-400 font-black font-mono text-lg sm:text-xl">{data.declines}</span>
                        </div>
                    </div>
                </div>
            </div>

            {/* 指數價格與漲跌幅 */}
            <div className="flex items-center justify-between w-full">
                <span className="text-4xl sm:text-5xl font-black tracking-tight font-mono">
                    {formatPrice(data.taiex_price)}
                </span>
                <div className="flex flex-col items-end gap-1 sm:gap-1.5 pt-0.5">
                    <span className={`text-xl sm:text-2xl font-black font-mono leading-none ${changeColor}`}>
                        {changeArrow} {Math.abs(data.taiex_change).toFixed(2)}
                    </span>
                    <span className={`text-lg sm:text-xl font-black font-mono leading-none ${changeColor} opacity-90`}>
                        {isUp ? '+' : ''}{data.taiex_change_percent.toFixed(2)}%
                    </span>
                </div>
            </div>
        </div>
    );
}
