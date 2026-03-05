import React from 'react'
import MarketSummary from '../components/MarketSummary'
import MarketRanking from '../components/MarketRanking'
import DailyInsights from '../components/DailyInsights'

export default function Home() {
  return (
    <>
      <div className="max-w-7xl mx-auto px-4 sm:px-6 lg:px-8 pt-4 sm:pt-6 pb-6 w-full">
        <section className="mb-4 sm:mb-6">
          <MarketSummary />
          <DailyInsights />
          <MarketRanking />
        </section>
      </div>
    </>
  )
}
