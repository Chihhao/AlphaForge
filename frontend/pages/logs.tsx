import React, { useState, useEffect, useRef } from 'react';
import Head from 'next/head';
import api from '../lib/api';

interface SystemEvent {
    id: number;
    level: 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS';
    message: string;
    category: string;
    timestamp: string;
}

interface DataStatus {
    stock_prices: string | null
    fundamentals: string | null
    chip_data: string | null
    stock_features: string | null
    alpha_signals: string | null
    strategy_picks: string | null
    pcr: string | null
    etf_flows: string | null
}

const STATUS_LABELS: Record<string, string> = {
    stock_prices: '行情', fundamentals: '基本面', chip_data: '籌碼',
    stock_features: '特徵', alpha_signals: '訊號', strategy_picks: '精選',
    pcr: 'PCR', etf_flows: 'ETF申贖',
}

function DataStatusBar({ status }: { status: DataStatus }) {
    const today = new Date().toISOString().slice(0, 10)
    return (
        <div className="flex flex-wrap gap-x-3 gap-y-1 px-1 pb-2 pt-1">
            {(Object.keys(STATUS_LABELS) as (keyof DataStatus)[]).map(key => {
                const val = status[key]
                const isToday = val === today
                const dateStr = val ? val.slice(5) : '—'  // MM-DD
                return (
                    <span key={key} className="flex items-center gap-1 text-[10px] font-mono">
                        <span className={`w-1.5 h-1.5 rounded-full shrink-0 ${isToday ? 'bg-emerald-400' : val ? 'bg-amber-400' : 'bg-zinc-700'}`} />
                        <span className="text-zinc-500">{STATUS_LABELS[key]}</span>
                        <span className={isToday ? 'text-emerald-400' : 'text-amber-500'}>{dateStr}</span>
                    </span>
                )
            })}
        </div>
    )
}

export default function LogsPage() {
    const [events, setEvents] = useState<SystemEvent[]>([]);
    const [dataStatus, setDataStatus] = useState<DataStatus | null>(null);
    const scrollRef = useRef<HTMLDivElement>(null);
    const isAtBottomRef = useRef(true);

    const handleScroll = () => {
        const el = scrollRef.current;
        if (!el) return;
        isAtBottomRef.current = el.scrollHeight - el.scrollTop - el.clientHeight < 40;
    };

    const fetchEvents = async () => {
        try {
            const response = await api.get('/market/system-events');
            setEvents(response.data);
        } catch (error) {
            console.error('Failed to fetch system events:', error);
        }
    };

    useEffect(() => {
        fetchEvents();
        api.get('/market/data-status').then(r => setDataStatus(r.data)).catch(() => {});
        const interval = setInterval(fetchEvents, 5000);
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (scrollRef.current && isAtBottomRef.current) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [events]);

    const getLevelIcon = (level: string) => {
        switch (level) {
            case 'SUCCESS': return (
                <svg className="w-4 h-4 text-emerald-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0 1 12 2.944a11.955 11.955 0 0 1-8.618 3.04M12 2.944V21m0-18.056L3.382 5.984m8.618-3.04l8.618 3.04M12 21l8.618-15.016M12 21L3.382 5.984" />
                </svg>
            );
            case 'WARNING': return (
                <svg className="w-4 h-4 text-amber-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
            );
            case 'ERROR': return (
                <svg className="w-4 h-4 text-rose-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
                </svg>
            );
            default: return (
                <svg className="w-4 h-4 text-cyan-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
                </svg>
            );
        }
    };

    const getLevelStyle = (level: string) => {
        switch (level) {
            case 'SUCCESS': return 'text-emerald-400/90';
            case 'WARNING': return 'text-amber-400/90';
            case 'ERROR': return 'text-rose-400/90';
            default: return 'text-zinc-400';
        }
    };

    return (
        <>
            <Head>
                <title>系統日誌 - AlphaForge</title>
            </Head>
            <div className="flex flex-col sm:max-w-4xl sm:mx-auto sm:px-4 sm:pt-6 sm:pb-12" style={{ height: 'calc(100dvh - 64px - 40px)' }}>
                {dataStatus && <DataStatusBar status={dataStatus} />}
                <div
                    ref={scrollRef}
                    onScroll={handleScroll}
                    className="bg-black/40 sm:border sm:border-white/10 sm:rounded-xl p-4 font-mono text-xs leading-relaxed custom-scrollbar overflow-y-auto flex-1 sm:min-h-[60vh] sm:max-h-[75vh]"
                >
                    {events.length === 0 ? (
                        <div className="text-zinc-600 italic px-2">Waiting for system events...</div>
                    ) : (
                        <div className="flex flex-col">
                            {(() => {
                                let lastDate = '';
                                return [...events].reverse().map((event) => {
                                    const dateObj = new Date(event.timestamp);
                                    const dateStr = `${dateObj.getFullYear()}/${dateObj.getMonth() + 1}/${dateObj.getDate()}`;
                                    const timeStr = dateObj.toLocaleTimeString([], { hour12: false, hour: '2-digit', minute: '2-digit' });

                                    const isNewDay = lastDate !== dateStr;
                                    lastDate = dateStr;

                                    return (
                                        <React.Fragment key={event.id}>
                                            {isNewDay && (
                                                <div className="flex items-center gap-2 py-3 px-1">
                                                    <div className="h-[1px] flex-grow bg-zinc-400/10" />
                                                    <div className="text-[9px] text-zinc-400 font-bold tabular-nums tracking-widest uppercase">{dateStr}</div>
                                                    <div className="h-[1px] flex-grow bg-zinc-400/10" />
                                                </div>
                                            )}
                                            <div className="grid grid-cols-[auto_auto_1fr] gap-x-2 py-0.5 items-center border-b border-white/[0.03] last:border-0">
                                                <div className="font-mono text-[10px] text-zinc-400 shrink-0 tabular-nums flex items-center gap-1.5">
                                                    <span className="hidden sm:inline opacity-70">{dateStr}</span>
                                                    <span className="font-bold">{timeStr}</span>
                                                </div>
                                                <div className="shrink-0 scale-90">{getLevelIcon(event.level)}</div>
                                                <div className={`${getLevelStyle(event.level)} text-[11px] sm:text-[12px] font-normal truncate tracking-tight`}>
                                                    <span className="text-zinc-400 font-bold text-[9px] mr-1">[{event.category}]</span>
                                                    {event.message}
                                                </div>
                                            </div>
                                        </React.Fragment>
                                    );
                                });
                            })()}
                            <div className="text-cyan-500/30 pt-2 animate-pulse px-1">_</div>
                        </div>
                    )}
                </div>
            </div>

            <style jsx global>{`
                .custom-scrollbar::-webkit-scrollbar { width: 6px; }
                .custom-scrollbar::-webkit-scrollbar-track { background: transparent; }
                .custom-scrollbar::-webkit-scrollbar-thumb { background: rgba(255,255,255,0.1); border-radius: 10px; }
                .custom-scrollbar::-webkit-scrollbar-thumb:hover { background: rgba(255,255,255,0.2); }
            `}</style>
        </>
    );
}
