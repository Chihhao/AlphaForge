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
    is_live: boolean;
    last_updated: string;
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
    const [flashClass, setFlashClass] = useState("");
    const prevPriceRef = React.useRef<number | null>(null);
    useEffect(() => {
        const fetchSummary = async () => {
            try {
                const res = await api.get('/market/summary');
                const newData = res.data;

                // 價格跳動動畫邏輯
                if (prevPriceRef.current !== null && newData.taiex_price !== prevPriceRef.current) {
                    const direction = newData.taiex_price > prevPriceRef.current ? "up" : "down";
                    setFlashClass(direction === "up" ? "bg-rose-500/20" : "bg-emerald-500/20");
                    setTimeout(() => setFlashClass(""), 800);
                }

                prevPriceRef.current = newData.taiex_price;
                setData(newData);
            } catch (err) {
                console.error('Failed to fetch market summary', err);
                setError(true);
            } finally {
                setLoading(false);
            }
        };

        fetchSummary();

        // 台灣時區處理：只有在交易時間 (平日 09:00 - 15:00) 才啟動輪詢
        const now = new Date();
        const day = now.getDay();
        const hour = now.getHours();
        const isTradingDay = day >= 1 && day <= 5;
        const isTradingHour = hour >= 9 && hour < 15;

        let interval: NodeJS.Timeout | null = null;
        if (isTradingDay && isTradingHour) {
            interval = setInterval(fetchSummary, 60000);
        }

        return () => {
            if (interval) clearInterval(interval);
        };
    }, []);

    if (loading) {
        return (
            <div className="bg-zinc-900/60 backdrop-blur-md rounded-2xl border border-white/5 p-6 animate-pulse">
                <div className="h-8 bg-zinc-700/50 rounded w-48 mb-3" />
                <div className="h-5 bg-zinc-700/50 rounded w-32" />
            </div>
        );
    }

    if (error || !data) {
        return (
            <div className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/5 p-5 text-center">
                <p className="text-zinc-500 text-sm">市場資料載入失敗，請稍後重試</p>
            </div>
        );
    }

    const isUp = data.taiex_change >= 0;
    // 台股習慣：紅漲綠跌
    const changeColor = isUp ? 'text-rose-500' : 'text-emerald-400';
    const changeArrow = isUp ? '▲' : '▼';

    return (
        <div className={`relative overflow-hidden bg-gradient-to-br ${isUp ? 'from-rose-900/20 to-zinc-900/80' : 'from-emerald-900/30 to-zinc-900/80'} backdrop-blur-md rounded-2xl border border-white/10 px-5 py-3.5 shadow-xl transition-colors duration-500 ${flashClass}`}>
            <div className="relative z-10 flex items-center justify-between gap-4">
                {/* 左：標題 + 價格 */}
                <div className="flex items-baseline gap-3 min-w-0">
                    <div className="flex items-center gap-1 shrink-0">
                        <span className="text-[10px] font-bold text-zinc-400 uppercase tracking-widest">加權指數</span>
                        <div className="inline-flex text-zinc-500 opacity-60 hover:opacity-100 transition-opacity">
                            <EducationalHint glossaryId="taiex" />
                        </div>
                    </div>
                    <span className="text-3xl sm:text-4xl font-black tracking-tight font-mono text-white leading-none">
                        {formatPrice(data.taiex_price)}
                    </span>
                </div>

                {/* 右：漲跌 + 次要資訊 */}
                <div className="flex flex-col items-end shrink-0 gap-0.5">
                    <div className="flex items-baseline gap-2">
                        <span className={`text-lg sm:text-xl font-black font-mono leading-none ${changeColor}`}>
                            {changeArrow} {Math.abs(data.taiex_change).toFixed(2)}
                        </span>
                        <span className={`text-base sm:text-lg font-black font-mono leading-none ${changeColor}`}>
                            {isUp ? '+' : ''}{data.taiex_change_percent.toFixed(2)}%
                        </span>
                    </div>
                    <div className="flex items-center gap-2 mt-0.5">
                        <div className={`w-1 h-1 rounded-full ${data.is_live ? 'bg-emerald-400/80 animate-pulse' : 'bg-zinc-600'}`} />
                        <span className="text-[10px] font-mono text-zinc-500">
                            {data.is_live ? `即時 ${data.last_updated}` : `收盤 ${data.data_date}`}
                        </span>
                        {data.volume_ratio > 0 && (
                            <>
                                <span className="text-zinc-700 text-[10px]">·</span>
                                <span className={`text-[10px] font-mono ${data.volume_status === 'high' ? 'text-amber-400' : 'text-zinc-500'}`}>
                                    量能 {data.volume_ratio.toFixed(2)}x {data.volume_status === 'high' ? '放量' : data.volume_status === 'low' ? '縮量' : '正常'}
                                </span>
                            </>
                        )}
                    </div>
                </div>
            </div>
        </div>
    );
}
