import React from 'react';
import Link from 'next/link';
import EducationalHint from './EducationalHint';

interface DummyStock {
    symbol: string;
    name: string;
    price: number;
    change: number;
    bias20: number;
}

interface DummyStrategy {
    id: string;
    name: string;
    description: string;
    tag: string;
    stocks: DummyStock[];
}

const dummyStrategies: DummyStrategy[] = [
    {
        id: 's1',
        name: '極限乖離抄底',
        description: '收盤價低於 20 日均線超過 10% (乖離率 < -10%)，尋找跌深超賣的潛在反彈標的。',
        tag: '逆勢策略',
        stocks: [
            { symbol: '3037', name: '欣興', price: 168.0, change: -2.3, bias20: -11.5 },
            { symbol: '2330', name: '台積電', price: 890.0, change: -1.5, bias20: -10.2 },
            { symbol: '2382', name: '廣達', price: 275.0, change: -3.5, bias20: -12.1 },
        ]
    },
    {
        id: 's2',
        name: '突破壓力區出量',
        description: '今日成交量大於 5 日均量 2 倍以上，且收盤價創近期新高，代表主力表態。',
        tag: '順勢動能',
        stocks: [
            { symbol: '2317', name: '鴻海', price: 155.0, change: 4.5, bias20: 3.2 },
            { symbol: '2454', name: '聯發科', price: 1120.0, change: 5.2, bias20: 4.8 },
        ]
    }
];

export default function StrategyScreener() {
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
                {dummyStrategies.map((strategy) => (
                    <div key={strategy.id} className="bg-zinc-900/40 backdrop-blur-md rounded-2xl border border-white/10 overflow-hidden shadow-xl hover:border-white/20 transition-all">
                        {/* 策略標題與說明 */}
                        <div className="p-5 border-b border-white/5 bg-white/[0.02]">
                            <div className="flex items-center justify-between mb-2">
                                <h3 className="text-xl font-bold text-white">{strategy.name}</h3>
                                <span className={`px-2.5 py-1 text-xs font-bold rounded-full ${strategy.tag === '逆勢策略' ? 'bg-rose-500/20 text-rose-400' : 'bg-emerald-500/20 text-emerald-400'
                                    }`}>
                                    {strategy.tag}
                                </span>
                            </div>
                            <p className="text-zinc-400 text-sm leading-relaxed">{strategy.description}</p>
                        </div>

                        {/* 股票清單 */}
                        <div className="p-2">
                            {strategy.stocks.map((stock) => {
                                const isUp = stock.change > 0;
                                const changeColor = isUp ? 'text-rose-400' : 'text-emerald-400';

                                return (
                                    <Link key={stock.symbol} href={`/stock/${stock.symbol}`} className="flex items-center justify-between p-3 rounded-xl hover:bg-white/5 transition-colors group cursor-pointer">
                                        <div className="flex items-center gap-4">
                                            <div className="w-10 h-10 rounded-full bg-zinc-800 flex items-center justify-center font-bold text-zinc-300 group-hover:bg-zinc-700 transition-colors">
                                                {stock.symbol.slice(0, 2)}
                                            </div>
                                            <div className="flex flex-col">
                                                <div className="flex items-center gap-2">
                                                    <span className="text-white font-bold">{stock.name}</span>
                                                    <span className="text-zinc-500 text-xs font-mono">{stock.symbol}</span>
                                                </div>
                                                <div className="flex items-center gap-1 mt-0.5" onClick={(e) => e.stopPropagation()}>
                                                    <span className="text-zinc-400 text-xs">20 日乖離率: <span className={stock.bias20 > 0 ? 'text-rose-400/80' : 'text-emerald-400/80'}>{stock.bias20 > 0 ? '+' : ''}{stock.bias20}%</span></span>
                                                    <div className="scale-75 origin-left">
                                                        <EducationalHint glossaryId="bias-indicator" />
                                                    </div>
                                                </div>
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
                            })}
                        </div>
                    </div>
                ))}
            </div>
        </div>
    );
}
