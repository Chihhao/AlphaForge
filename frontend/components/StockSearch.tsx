import React, { useState } from 'react'

interface StockSearchProps {
  onSearch: (symbol: string) => void
}

export default function StockSearch({ onSearch }: StockSearchProps) {
  const [input, setInput] = useState('')

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault()
    if (input.trim()) {
      onSearch(input)
      setInput('')
    }
  }

  return (
    <form onSubmit={handleSubmit} className="w-full max-w-3xl mx-auto group">
      <div className="relative flex items-center w-full h-16 sm:h-20 rounded-full focus-within:shadow-2xl bg-gray-800 overflow-hidden shadow-lg transition-all duration-300 border border-gray-700">
        <div className="grid place-items-center h-full w-16 sm:w-20 text-gray-400 group-focus-within:text-gold-500 transition-colors">
          <svg xmlns="http://www.w3.org/2000/svg" className="h-6 w-6 sm:h-8 sm:w-8" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth="2" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
          </svg>
        </div>

        <input
          className="peer h-full w-full outline-none text-lg sm:text-xl text-gray-100 bg-transparent pr-2 placeholder-gray-500"
          type="text"
          placeholder="輸入股票代號或名稱 (例：2330 或 台積電)"
          value={input}
          onChange={(e) => setInput(e.target.value)}
        />

        <button
          type="submit"
          className="h-full px-6 sm:px-10 bg-gold-600 text-gray-900 font-semibold hover:bg-gold-500 transition-colors duration-300 text-lg sm:text-xl"
        >
          搜尋
        </button>
      </div>
    </form>
  )
}
