import React, { useState, useEffect } from 'react'

interface StockSearchProps {
  onSearch: (symbol: string) => void
}

export default function StockSearch({ onSearch }: StockSearchProps) {
  const [input, setInput] = useState('')
  const [placeholder, setPlaceholder] = useState('輸入股票代號或名稱 (例：2330)')

  useEffect(() => {
    const handleResize = () => {
      if (window.innerWidth < 640) {
        setPlaceholder('輸入股票代號或名稱')
      } else {
        setPlaceholder('輸入股票代號或名稱 (例：2330)')
      }
    }

    handleResize()
    window.addEventListener('resize', handleResize)
    return () => window.removeEventListener('resize', handleResize)
  }, [])

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim()) {
      onSearch(input)
      setInput('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-3xl mx-auto group">
      <div className="relative flex items-center w-full h-16 sm:h-20 rounded-2xl bg-brand-dark overflow-hidden transition-all duration-300 border border-zinc-800 focus-within:border-emerald-500/50">
        <div className="grid place-items-center h-full w-16 sm:w-20 text-neutral-500 group-focus-within:text-emerald-400 transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="h-6 w-6 sm:h-7 sm:w-7">
            <circle cx="11" cy="11" r="8"></circle>
            <line x1="21" y1="21" x2="16.65" y2="16.65"></line>
          </svg>
        </div>

        <input
          className="peer h-full w-full outline-none text-xl sm:text-2xl text-neutral-50 bg-transparent pr-2 placeholder-neutral-600 font-mono"
          type="text"
          placeholder={placeholder}
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />

        <button
          type="submit"
          className="h-full px-6 sm:px-10 bg-neutral-50 text-black font-bold hover:bg-neutral-200 active:bg-neutral-300 transition-all duration-300 text-xl sm:text-2xl flex-shrink-0 whitespace-nowrap"
        >
          搜尋
        </button>
      </div>
    </form>
  )
}
