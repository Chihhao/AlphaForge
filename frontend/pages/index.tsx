import Head from 'next/head';
import MarketSummary from '../components/MarketSummary';
import StrategyScreener from '../components/StrategyScreener';
import StrategyMinerPreview from '../components/StrategyMinerPreview';
import MarketSentimentWidget from '../components/MarketSentimentWidget';
import MarketRanking from '../components/MarketRanking';
import WatchlistWidget from '../components/WatchlistWidget';

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

        {/* 強弱排行榜 */}
        <section className="mb-4">
          <MarketRanking />
        </section>

        {/* 今日操作建議：Strategy Miner 精簡預覽 */}
        <section className="mb-4">
          <StrategyMinerPreview />
        </section>

        {/* 觀察清單（localStorage，有內容才顯示）*/}
        <section className="mb-4">
          <WatchlistWidget />
        </section>

        {/* 市場情緒：ETF 申贖資金流向 */}
        <section className="mb-4">
          <MarketSentimentWidget />
        </section>

        {/* 單欄佈局：全寬度的選股雷達 */}
        <section className="w-full">
          <StrategyScreener />
        </section>
      </div>
    </>
  )
}
