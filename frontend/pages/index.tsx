import Head from 'next/head';
import MarketSummary from '../components/MarketSummary';
import StrategyScreener from '../components/StrategyScreener';

export default function Home() {

  return (
    <>
      <Head>
        <title>AlphaForge - 量化儀表板</title>
      </Head>
      <div className="max-w-[1600px] mx-auto px-4 pt-4 pb-12 w-full min-h-screen">

        {/* 頂部：大盤溫度計 (Market Pulse) */}
        <section className="mb-4">
          <MarketSummary />
        </section>

        {/* 單欄佈局：全寬度的選股雷達 */}
        <section className="w-full">
          <StrategyScreener />
        </section>
      </div>
    </>
  )
}
