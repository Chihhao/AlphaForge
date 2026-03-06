import React from 'react'
import Link from 'next/link'

import { formatPrice } from '../lib/formatters'

interface StockCardProps {
    stock: {
        id: string
        name: string
        price: number
        change: number
    }
}

export default function StockCard({ stock }: StockCardProps) {
    const isPositive = stock.change >= 0
    const changeColor = isPositive ? 'text-rose-500' : 'text-emerald-400'

    return (
        <Link
            href={`/stock/${stock.id}`}
            className="flex items-center justify-between p-5 transition-all hover:bg-white/5 bg-zinc-900/40 backdrop-blur-md border border-zinc-800/50 border-l-4 border-l-cyan-400 group shadow-lg"
        >
            <div className="flex items-center gap-6">
                <div className="flex flex-col">
                    <span className="font-bold text-neutral-100 text-xl tracking-wide group-hover:text-cyan-400 transition-colors">{stock.name}</span>
                    <span className="text-base text-neutral-500 font-mono tracking-widest mt-1">{stock.id}</span>
                </div>
            </div>
            <div className="text-right flex flex-col justify-center">
                <span className="font-bold text-neutral-50 text-xl font-mono">{formatPrice(stock.price)}</span>
                <span className={`text-base font-mono font-bold tracking-widest mt-1 ${changeColor}`}>
                    {isPositive ? '▲' : '▼'} {Math.abs(stock.change).toFixed(2)}%
                </span>
            </div>
        </Link>
    )
}
