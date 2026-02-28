import React, { useState, useEffect } from 'react';
import Link from 'next/link';
import api from '../lib/api';
import EducationalHint from './EducationalHint';

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

export default function MarketRanking() {
    const [data, setData] = useState<MarketRankingResponse | null>(null);
    const [loading, setLoading] = useState(true);

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
            <div className="w-full flex justify-center items-center py-16">
                <div className="animate-spin h-8 w-8 text-emerald-400 rounded-full border-b-2 border-emerald-400"></div>
            </div>
        );
    }

    if (!data) return null;

    const renderList = (title: string, hintTitle: string, hintDesc: string, items: RankingItem[], type: 'gainer' | 'loser' | 'volume') => (
        <div className="bg-gradient-to-b from-zinc-900/50 to-zinc-950/80 backdrop-blur-md p-6 rounded-xl flex flex-col h-full border border-zinc-800/50 hover:border-zinc-700/80 transition-all duration-500 shadow-2xl group/card">
            <div className="flex items-center justify-between mb-6 pb-4 border-b border-zinc-900">
                <h3 className="text-2xl font-bold text-neutral-50 flex items-center tracking-tight">
                    {title}
                    <EducationalHint title={hintTitle} description={hintDesc} />
                </h3>
            </div>

            <div className="flex-grow flex flex-col gap-3">
                {items.map((item, index) => {
                    const isGainer = item.change_percent >= 0;
                    const valueColor = isGainer ? 'text-emerald-400' : 'text-rose-500';
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
                                <span className="font-bold text-neutral-50 text-xl font-mono">{item.price.toFixed(2)}</span>
                                {type === 'volume' ? (
                                    <span className="text-base font-mono text-cyan-500 font-medium tracking-widest mt-1">
                                        {(item.volume / 1000).toFixed(1)}K 張
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
        </div>
    );

    return (
        <div className="grid grid-cols-1 md:grid-cols-3 gap-4 md:gap-6 w-full">
            {renderList(
                "強勢漲幅榜",
                "什麼是強勢漲幅？",
                "這代表今天買氣最強、價格上漲最多的股票。新手可以觀察它們背後是否有重大利多消息，但要注意追高的風險喔！",
                data.top_gainers,
                "gainer"
            )}
            {renderList(
                "弱勢跌幅榜",
                "跌幅榜能告訴我們什麼？",
                "這裡列出今天賣壓最重、跌幅最大的股票。這些公司可能正經歷利空打擊，或者是漲多後的回檔修正。從中可以學習避開市場雷區。",
                data.top_losers,
                "loser"
            )}
            {renderList(
                "爆量人氣榜",
                "為什麼成交量大很重要？",
                "「新手看價，老手看量」。成交量大代表市場對這檔股票的關注度極高，不管買方還是賣方都非常積極，通常也是趨勢轉折或延續的關鍵指標！",
                data.top_volume,
                "volume"
            )}
        </div>
    );
}
