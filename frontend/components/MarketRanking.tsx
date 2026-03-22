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
                const res = await api.get('/stocks/rankings?limit=5');
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
        <div className="flex-grow flex flex-col gap-3">
            {items.map((item, index) => {
                const isGainer = item.change_percent >= 0;
                const valueColor = isGainer ? 'text-rose-500' : 'text-emerald-400';
                const bgHighlight = index < 3 ? 'bg-zinc-900/50' : '';
                const borderHighlight = index === 0 ? 'border-l-4 border-l-cyan-400' : 'border-l-4 border-l-transparent';

                return (
                    <Link
                        key={item.stock_id}
                        href={`/stock/${item.stock_id}`}
                        className={`flex items-center justify-between p-4 transition-all hover:bg-white/5 active:scale-[0.98] ${bgHighlight} ${borderHighlight}`}
                    >
                        <div className="flex items-center gap-4">
                            <span className={`font-mono font-bold text-xl w-6 text-center ${index < 3 ? 'text-cyan-400' : 'text-neutral-600'}`}>
                                {index + 1}
                            </span>
                            <div className="flex flex-col">
                                <span className="font-bold text-neutral-100 text-xl tracking-wide">{item.stock_name}</span>
                                <span className="text-base text-neutral-500 font-mono tracking-widest mt-1">{item.stock_id}</span>
                            </div>
                        </div>
                        <div className="text-right flex flex-col justify-center">
                            <span className="font-bold text-neutral-50 text-xl font-mono">{formatPrice(item.price)}</span>
                            {type === 'volume' ? (
                                <span className="text-base font-mono text-cyan-500 font-medium tracking-widest mt-1">
                                    {(() => {
                                        const lots = item.volume / 1000;
                                        return lots >= 10000
                                            ? (lots / 10000).toFixed(2) + ' 萬張'
                                            : Math.floor(lots).toLocaleString() + ' 張';
                                    })()}
                                </span>
                            ) : (
                                <span className={`text-base font-mono font-bold tracking-widest mt-1 ${valueColor}`}>
                                    {isGainer ? '▲' : '▼'} {Math.abs(item.change_percent).toFixed(2)}%
                                </span>
                            )}
                        </div>
                    </Link>
                );
            })}
            {items.length === 0 && (
                <div className="text-neutral-500 text-center py-10 text-base bg-zinc-900/20 border border-dashed border-zinc-800/50 rounded-lg">
                    目前無資料
                </div>
            )}
        </div>
    );

    const renderCard = (title: string, glossaryId: string, items: RankingItem[], type: 'gainer' | 'loser' | 'volume') => (
        <div className="bg-gradient-to-b from-zinc-900/50 to-zinc-950/80 backdrop-blur-md p-6 rounded-xl flex flex-col h-full border border-zinc-800/50 hover:border-zinc-700/80 transition-all duration-500 shadow-2xl">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-900">
                <h3 className="text-2xl font-bold text-neutral-50 flex items-center tracking-tight">
                    {title}
                    <div className="inline-flex text-zinc-400 opacity-50 hover:opacity-100 transition-opacity ml-2">
                        <EducationalHint glossaryId={glossaryId} />
                    </div>
                </h3>
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
            <div className="md:hidden bg-gradient-to-b from-zinc-900/50 to-zinc-950/80 backdrop-blur-md rounded-xl border border-zinc-800/50 shadow-2xl overflow-hidden">
                {/* Tab bar */}
                <div className="flex border-b border-zinc-800/80">
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
                </div>
                {/* Content */}
                <div className="p-4">
                    {renderItems(tabItems[activeTab].items, tabItems[activeTab].type)}
                </div>
            </div>
        </>
    );
}
