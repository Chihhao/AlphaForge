'use client';

import React, { useState, useEffect, useRef } from 'react';
import api from '../lib/api';


interface SystemEvent {
    id: number;
    level: 'INFO' | 'WARNING' | 'ERROR' | 'SUCCESS';
    message: string;
    category: string;
    timestamp: string;
}

const SystemConsole: React.FC = () => {
    const [events, setEvents] = useState<SystemEvent[]>([]);
    const [isExpanded, setIsExpanded] = useState(false);
    const [isLoading, setIsLoading] = useState(false);
    const scrollRef = useRef<HTMLDivElement>(null);
    const containerRef = useRef<HTMLDivElement>(null);

    useEffect(() => {
        const handleClickOutside = (event: MouseEvent) => {
            if (containerRef.current && !containerRef.current.contains(event.target as Node)) {
                setIsExpanded(false);
            }
        };

        if (isExpanded) {
            document.addEventListener('mousedown', handleClickOutside);
        }

        return () => {
            document.removeEventListener('mousedown', handleClickOutside);
        };
    }, [isExpanded]);

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
        const interval = setInterval(fetchEvents, 5000); // 每 5 秒輪詢一次
        return () => clearInterval(interval);
    }, []);

    useEffect(() => {
        if (scrollRef.current && isExpanded) {
            scrollRef.current.scrollTop = scrollRef.current.scrollHeight;
        }
    }, [events, isExpanded]);

    const getLevelIcon = (level: string) => {
        switch (level) {
            case 'SUCCESS': return (
                <svg className="w-4 h-4 text-emerald-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0 1 12 2.944a11.955 11.955 0 0 1-8.618 3.04M12 2.944V21m0-18.056L3.382 5.984m8.618-3.04l8.618 3.04M12 21l8.618-15.016M12 21L3.382 5.984" />
                </svg>
            );
            case 'WARNING': return (
                <svg className="w-4 h-4 text-amber-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-3L13.732 4c-.77-1.333-2.694-1.333-3.464 0L3.34 16c-.77 1.333.192 3 1.732 3z" />
                </svg>
            );
            case 'ERROR': return (
                <svg className="w-4 h-4 text-rose-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 8v4m0 4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
                </svg>
            );
            default: return (
                <svg className="w-4 h-4 text-cyan-400" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M13 16h-1v-4h-1m1-4h.01M21 12a9 9 0 1 1-18 0 9 9 0 0 1 18 0z" />
                </svg>
            );
        }
    };

    const getLevelText = (level: string) => {
        switch (level) {
            case 'SUCCESS': return '完成';
            case 'WARNING': return '警報';
            case 'ERROR': return '錯誤';
            default: return '資訊';
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

    const handleManualSync = async () => {
        setIsLoading(true);
        try {
            await api.post('/market/sync/daily');
            fetchEvents();
            setIsExpanded(true);
        } catch (error) {
            console.error('Manual sync failed:', error);
        } finally {
            setIsLoading(false);
        }
    };

    return (
        <div
            ref={containerRef}
            className={`fixed bottom-0 left-0 right-0 z-40 transition-all duration-300 ${isExpanded ? 'h-64' : 'h-10'
                } bg-zinc-950/90 backdrop-blur-xl border-t border-white/10 flex flex-col shadow-[0_-10px_30px_rgba(0,0,0,0.5)]`}>

            {/* 標題欄 / 切換器 */}
            <div
                className="flex items-center justify-between px-4 h-10 cursor-pointer hover:bg-white/5 transition-colors border-b border-white/5"
                onClick={() => setIsExpanded(!isExpanded)}
            >
                <div className="flex items-center gap-2 max-w-[70%]">
                    <svg className="w-4 h-4 text-cyan-400 shrink-0" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                        <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 0 0 2-2V6a2 2 0 0 0-2-2H5a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2z" />
                    </svg>
                    <span className="text-[10px] sm:text-xs font-mono font-bold text-zinc-400 tracking-wider uppercase flex items-center gap-1.5 shrink-0">
                        CONSOLE
                        {events.length > 0 && (
                            <span className={`w-1 h-1 sm:w-1.5 sm:h-1.5 rounded-full bg-emerald-500 animate-pulse`} />
                        )}
                    </span>
                    {!isExpanded && events.length > 0 && (
                        <>
                            <span className="text-[#333] hidden sm:inline">|</span>
                            <span className="text-[10px] text-zinc-500 font-mono truncate opacity-80">
                                {events[0].message}
                            </span>
                        </>
                    )}
                </div>

                <div className="flex items-center gap-4">
                    <button
                        onClick={(e) => {
                            e.stopPropagation();
                            handleManualSync();
                        }}
                        disabled={isLoading}
                        className="flex items-center gap-1 px-2 py-1 rounded bg-cyan-500/10 hover:bg-cyan-500/20 text-cyan-400 text-[10px] transition-all disabled:opacity-50 whitespace-nowrap shrink-0"
                    >
                        <svg className={`w-3 h-3 ${isLoading ? 'animate-spin' : ''}`} fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 4v5h.582m15.356 2A8.001 8.001 0 004.582 9m0 0H9m11 11v-5h-.581m0 0a8.003 8.003 0 01-15.357-2m15.357 2H15" />
                        </svg>
                        Sync Now
                    </button>
                    {isExpanded ? (
                        <svg className="w-4 h-4 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M19 9l-7 7-7-7" />
                        </svg>
                    ) : (
                        <svg className="w-4 h-4 text-zinc-500" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M5 15l7-7 7 7" />
                        </svg>
                    )}
                </div>
            </div>

            {/* 紀錄內容區 */}
            {isExpanded && (
                <div
                    ref={scrollRef}
                    className="flex-grow overflow-y-auto p-4 font-mono text-xs leading-relaxed custom-scrollbar bg-black/40"
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
                                                    <div className="h-[1px] flex-grow bg-zinc-400/10"></div>
                                                    <div className="text-[9px] text-zinc-400 font-bold tabular-nums tracking-widest uppercase">{dateStr}</div>
                                                    <div className="h-[1px] flex-grow bg-zinc-400/10"></div>
                                                </div>
                                            )}
                                            <div className="grid grid-cols-[auto_auto_1fr] gap-x-2 py-0.5 items-center border-b border-white/[0.03] last:border-0 animate-in fade-in slide-in-from-left-2 duration-300 overflow-hidden">
                                                {/* 時間欄位 - 手機隱藏日期 */}
                                                <div className="font-mono text-[10px] text-zinc-400 shrink-0 tabular-nums flex items-center gap-1.5">
                                                    <span className="hidden sm:inline opacity-70">{dateStr}</span>
                                                    <span className="font-bold">{timeStr}</span>
                                                </div>

                                                {/* 圖示欄位 - 保留等級辨識色 */}
                                                <div className="shrink-0 scale-90">
                                                    {getLevelIcon(event.level)}
                                                </div>

                                                {/* 訊息內容 - 成功綠，其餘統一灰色 */}
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
            )}

            <style jsx global>{`
        .custom-scrollbar::-webkit-scrollbar {
          width: 6px;
        }
        .custom-scrollbar::-webkit-scrollbar-track {
          background: transparent;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb {
          background: rgba(255, 255, 255, 0.1);
          border-radius: 10px;
        }
        .custom-scrollbar::-webkit-scrollbar-thumb:hover {
          background: rgba(255, 255, 255, 0.2);
        }
      `}</style>
        </div>
    );
};

export default SystemConsole;
