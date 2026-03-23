import React, { useState, useEffect } from 'react';
import api from '../lib/api';
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
        <div className={`overflow-hidden bg-gradient-to-br ${isUp ? 'from-rose-900/20 to-zinc-900/80' : 'from-emerald-900/30 to-zinc-900/80'} backdrop-blur-md rounded-2xl border border-white/10 px-4 py-3 shadow-xl transition-colors duration-500 ${flashClass}`}>
            {/* Row 1: 標題 + 狀態 */}
            <div className="flex items-center justify-between mb-1.5">
                <span className="text-sm font-bold text-zinc-200 uppercase tracking-widest">加權指數</span>
                <div className="flex items-center gap-1.5">
                    <div className={`w-1.5 h-1.5 rounded-full shrink-0 ${data.is_live ? 'bg-emerald-400/80 animate-pulse' : 'bg-zinc-600'}`} />
                    <span className="text-[10px] font-mono text-zinc-400">
                        {data.is_live ? `即時 ${data.last_updated}` : `收盤 ${data.data_date}`}
                    </span>
                </div>
            </div>

            {/* Row 2: 價格（左）＋ 漲跌（右） */}
            <div className="flex items-center justify-between gap-3">
                <span className="text-4xl font-black tracking-tight font-mono text-white leading-none shrink-0">
                    {formatPrice(data.taiex_price)}
                </span>
                <div className="flex flex-col items-end shrink-0">
                    <span className={`text-xl font-black font-mono leading-tight ${changeColor}`}>
                        {changeArrow} {Math.abs(data.taiex_change).toFixed(2)}
                    </span>
                    <span className={`text-base font-black font-mono leading-tight ${changeColor}`}>
                        {isUp ? '+' : ''}{data.taiex_change_percent.toFixed(2)}%
                    </span>
                </div>
            </div>
        </div>
    );
}
