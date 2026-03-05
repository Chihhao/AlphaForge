import React, { useState, useEffect } from 'react';
import EducationalHint from './EducationalHint';

export default function DailyInsights() {
    const [mounted, setMounted] = useState(false);

    useEffect(() => {
        setMounted(true);
    }, []);

    const today = mounted ? new Date().toLocaleDateString('zh-TW', {
        year: 'numeric',
        month: 'long',
        day: 'numeric',
        weekday: 'long'
    }) : '';

    return (
        <div className="mb-8 mt-2">
            {/* 今日盤勢概況 */}
            <div className="w-full bg-gradient-to-br from-indigo-900/40 to-emerald-900/20 backdrop-blur-md p-6 rounded-2xl border border-white/10 shadow-xl flex flex-col justify-center">
                <div className="flex items-center gap-3 mb-2">
                    <h2 className="text-zinc-400 text-sm font-medium tracking-widest">{today}</h2>
                </div>
                <h1 className="text-3xl sm:text-4xl font-black text-white mb-3 tracking-tight">
                    市場觀測：<span className="inline-block bg-clip-text text-transparent bg-gradient-to-r from-emerald-400 to-cyan-400">平均持有成本</span>
                </h1>
                <p className="text-zinc-400 text-lg leading-relaxed max-w-2xl">
                    移動平均線 (MA) 反映了市場參與者的平均共識。當股價站在均線之上，代表多方正掌握主導權；反之則需留意賣壓趨勢。
                </p>
            </div>
        </div>
    );
}
