import React from 'react'

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
  const changeColor = isPositive ? 'text-green-600' : 'text-red-600'
  const changeBgColor = isPositive ? 'bg-green-50' : 'bg-red-50'

  return (
    <div className="bg-white rounded-lg shadow hover:shadow-lg transition p-6 cursor-pointer">
      <div className="mb-4">
        <h3 className="text-lg font-bold text-gray-800">{stock.name}</h3>
        <p className="text-sm text-gray-500">{stock.id}</p>
      </div>
      <div className="flex justify-between items-end">
        <div>
          <p className="text-2xl font-bold text-gray-800">NT${stock.price.toFixed(2)}</p>
        </div>
        <div className={`${changeBgColor} px-3 py-1 rounded ${changeColor} font-semibold`}>
          {isPositive ? '+' : ''}{stock.change.toFixed(2)}%
        </div>
      </div>
    </div>
  )
}
