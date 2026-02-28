import React from 'react'
import MarketRanking from '../components/MarketRanking'

export default function Home() {
  return (
    <>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-6 pb-6 w-full">
        <section className="mb-4 sm:mb-6">
          <MarketRanking />
        </section>
      </div>
    </>
  )
}
