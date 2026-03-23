import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import api from '../lib/api';
import EducationalHint from './EducationalHint';
import { formatPrice } from '../lib/formatters';

interface RankingItem {
    stock_id: string;
    stock_name: string;
    price: number;
    change_percent: number;
    volume: number;
}

interface MarketRankingResponse {
    top_gainers: RankingItem[];
    top_losers: RankingItem[];
    top_volume: RankingItem[];
    data_date?: string;
}

type TabKey = 'gainers' | 'losers' | 'volume'

const TAB_CONFIG: { key: TabKey; label: string; shortLabel: string }[] = [
    { key: 'gainers', label: '強勢漲幅榜', shortLabel: '漲幅' },
    { key: 'losers',  label: '弱勢跌幅榜', shortLabel: '跌幅' },
    { key: 'volume',  label: '爆量人氣榜', shortLabel: '人氣' },
]

export default function MarketRanking() {
    const [data, setData] = useState<MarketRankingResponse | null>(null);
    const [loading, setLoading] = useState(true);
    const [activeTab, setActiveTab] = useState<TabKey>('gainers');

    useEffect(() => {
        const fetchRankings = async () => {
            try {
                const res = await api.get('/stocks/rankings?limit=30');
                setData(res.data);
            } catch (error) {
                console.error('Failed to fetch rankings', error);
            } finally {
                setLoading(false);
            }
        };
        fetchRankings();
    }, []);

    if (loading) {
        return (
            <div className="w-full flex justify-center items-center py-8">
                <div className="animate-spin h-6 w-6 rounded-full border-b-2 border-emerald-400"></div>
            </div>
        );
    }

    if (!data) return null;

    const renderItems = (items: RankingItem[], type: 'gainer' | 'loser' | 'volume') => (
        <div className="overflow-y-auto max-h-[22rem] flex flex-col">
            {items.map((item, index) => {
                const isGainer = item.change_percent >= 0;
                const valueColor = isGainer ? 'text-rose-400' : 'text-emerald-400';

                return (
                    <Link
                        key={item.stock_id}
                        href={`/stock/${item.stock_id}`}
                        className="flex items-center justify-between py-2.5 px-2 rounded-lg hover:bg-white/5 transition-colors border-b border-zinc-800/40 last:border-b-0 active:scale-[0.98]"
                    >
                        <div className="flex items-center gap-3">
                            <span className={`font-mono font-bold text-xs w-4 text-center ${index < 3 ? 'text-cyan-400' : 'text-zinc-600'}`}>
                                {index + 1}
                            </span>
                            <div className="flex flex-col">
                                <span className="text-sm font-semibold text-zinc-100">{item.stock_name}</span>
                                <span className="text-xs text-zinc-500 font-mono">{item.stock_id}</span>
                            </div>
                        </div>
                        <div className="text-right flex flex-col justify-center">
                            <span className="text-sm font-bold text-zinc-100 font-mono">{formatPrice(item.price)}</span>
                            {type === 'volume' ? (
                                <span className="text-xs font-mono text-cyan-400 font-bold">
                                    {(() => {
                                        const lots = item.volume / 1000;
                                        return lots >= 10000
                                            ? (lots / 10000).toFixed(2) + ' 萬張'
                                            : Math.floor(lots).toLocaleString() + ' 張';
                                    })()}
                                </span>
                            ) : (
                                <span className={`text-xs font-mono font-bold ${valueColor}`}>
                                    {isGainer ? '▲' : '▼'} {Math.abs(item.change_percent).toFixed(2)}%
                                </span>
                            )}
                        </div>
                    </Link>
                );
            })}
            {items.length === 0 && (
                <div className="text-zinc-500 text-center py-8 text-sm bg-zinc-900/20 border border-dashed border-zinc-800/50 rounded-lg">
                    目前無資料
                </div>
            )}
        </div>
    );

    const dateLabel = data?.data_date
        ? `${data.data_date.slice(5).replace('-', '/')} 收盤`
        : ''

    const renderCard = (title: string, glossaryId: string, items: RankingItem[], type: 'gainer' | 'loser' | 'volume') => (
        <div className="bg-zinc-900/60 border border-white/10 rounded-2xl px-4 py-3 flex flex-col">
            <div className="flex items-center justify-between mb-2 pb-2 border-b border-zinc-800/40">
                <div className="flex items-center gap-2">
                    <span className="text-[10px] font-bold text-zinc-500 uppercase tracking-widest">{title}</span>
                    <div className="text-zinc-600 opacity-60 hover:opacity-100 transition-opacity">
                        <EducationalHint glossaryId={glossaryId} />
                    </div>
                </div>
                {dateLabel && (
                    <span className="text-[10px] font-mono text-zinc-500">{dateLabel}</span>
                )}
            </div>
            {renderItems(items, type)}
        </div>
    );

    const tabItems: Record<TabKey, { title: string; glossaryId: string; items: RankingItem[]; type: 'gainer' | 'loser' | 'volume' }> = {
        gainers: { title: '強勢漲幅榜', glossaryId: 'strong-uptrend', items: data.top_gainers, type: 'gainer' },
        losers:  { title: '弱勢跌幅榜', glossaryId: 'weak-downtrend', items: data.top_losers,  type: 'loser' },
        volume:  { title: '爆量人氣榜', glossaryId: 'high-volume',    items: data.top_volume,  type: 'volume' },
    }

    return (
        <>
            {/* 桌面版：三欄 grid */}
            <div className="hidden md:grid grid-cols-3 gap-6 w-full">
                {renderCard('強勢漲幅榜', 'strong-uptrend', data.top_gainers, 'gainer')}
                {renderCard('弱勢跌幅榜', 'weak-downtrend', data.top_losers,  'loser')}
                {renderCard('爆量人氣榜', 'high-volume',    data.top_volume,  'volume')}
            </div>

            {/* 行動端：tab 切換 */}
            <div className="md:hidden bg-zinc-900/60 border border-white/10 rounded-2xl overflow-hidden">
                {/* Tab bar */}
                <div className="flex items-center border-b border-zinc-800/80">
                    {TAB_CONFIG.map(tab => (
                        <button
                            key={tab.key}
                            onClick={() => setActiveTab(tab.key)}
                            className={`flex-1 py-3 text-sm font-semibold transition-colors cursor-pointer ${
                                activeTab === tab.key
                                    ? 'text-white border-b-2 border-cyan-400 bg-white/5'
                                    : 'text-zinc-500 hover:text-zinc-300'
                            }`}
                        >
                            {tab.shortLabel}
                        </button>
                    ))}
                    {dateLabel && (
                        <span className="text-[10px] font-mono text-zinc-500 px-3 shrink-0">{dateLabel}</span>
                    )}
                </div>
                {/* Content */}
                <div className="px-2 py-1">
                    {renderItems(tabItems[activeTab].items, tabItems[activeTab].type)}
                </div>
            </div>
        </>
    );
}
