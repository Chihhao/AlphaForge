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

export default function LogsPage() {
    const [events, setEvents] = useState<SystemEvent[]>([]);
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
            <div className="max-w-4xl mx-auto px-4 pt-6 pb-12">
                <div className="flex items-center justify-between mb-4">
                    <div className="flex items-center gap-2">
                        <svg className="w-5 h-5 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
                        </svg>
                        <h1 className="text-sm font-mono font-bold text-zinc-400 tracking-wider uppercase">SYSTEM CONSOLE</h1>
                        {events.length > 0 && (
                            <span className="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse" />
                        )}
                    </div>
                </div>

                <div
                    ref={scrollRef}
                    onScroll={handleScroll}
                    className="bg-black/40 border border-white/10 rounded-xl p-4 font-mono text-xs leading-relaxed custom-scrollbar min-h-[60vh] max-h-[75vh] overflow-y-auto"
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
