import React, { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import Head from 'next/head'
import { useRouter } from 'next/router'

interface LayoutProps {
    children: React.ReactNode
}

interface SearchHistoryItem {
    symbol: string
    name?: string
}

const DEFAULT_HOT_SEARCHES: SearchHistoryItem[] = [
    { symbol: '2330', name: '台積電' },
    { symbol: '2454', name: '聯發科' },
    { symbol: '2317', name: '鴻海' },
    { symbol: '0050', name: '台灣50' },
    { symbol: '2603', name: '長榮' }
]

const SVGPresenter = ({ path, size = 24, className = "" }: { path: string, size?: number, className?: string }) => (
    <svg
        viewBox="0 0 24 24"
        width={size}
        height={size}
        className={`fill-current ${className}`}
    >
        <path d={path} />
    </svg>
)

const Layout: React.FC<LayoutProps> = ({ children }) => {
    const router = useRouter()
    const [isSidebarOpen, setSidebarOpen] = useState(false)
    const [isSearchOpen, setSearchOpen] = useState(false)
    const [searchInput, setSearchInput] = useState('')
    const searchInputRef = useRef<HTMLInputElement>(null)
    const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([])

    useEffect(() => {
        try {
            const saved = localStorage.getItem('alphaforge_search_history')
            if (saved) {
                setSearchHistory(JSON.parse(saved))
            }
        } catch (e) {
            console.error('Failed to load search history', e)
        }
    }, [])

    const addSearchHistory = (symbol: string, name?: string) => {
        const newItem: SearchHistoryItem = { symbol, name }
        setSearchHistory(prev => {
            const filtered = prev.filter(item => item.symbol !== symbol)
            const updated = [newItem, ...filtered].slice(0, 10)
            localStorage.setItem('alphaforge_search_history', JSON.stringify(updated))
            return updated
        })
    }

    useEffect(() => {
        if (isSearchOpen && searchInputRef.current) {
            setTimeout(() => searchInputRef.current?.focus(), 100);
        }
    }, [isSearchOpen])

    // Standard paths for MDI icons
    const icons = {
        menu: "M3,6H21V8H3V6M3,11H21V13H3V11M3,16H21V18H3V16Z",
        close: "M19,6.41L17.59,5L12,10.59L6.41,5L5,6.41L10.59,12L5,17.59L6.41,19L12,13.41L17.59,19L19,17.59L13.41,12L19,6.41Z",
        magnify: "M9.5,3A6.5,6.5 0 0,1 16,9.5C16,11.11 15.41,12.59 14.44,13.73L14.71,14H15.5L20.5,19L19,20.5L14,15.5V14.71L13.73,14.44C12.59,15.41 11.11,16 9.5,16A6.5,6.5 0 0,1 3,9.5A6.5,6.5 0 0,1 9.5,3M9.5,5A4.5,4.5 0 0,0 5,9.5A4.5,4.5 0 0,0 9.5,14A4.5,4.5 0 0,0 14,9.5A4.5,4.5 0 0,0 9.5,5Z",
        home: "M10,20V14H14V20H19V12H22L12,3L2,12H5V20H10Z",
        chart: "M11,2V22C5.9,21.5 2,17.2 2,12C2,6.8 5.9,2.5 11,2M13,2C13.5,2 14,2 14.5,2.1L13,11V2M15.4,3.3C18.9,5.2 21.3,8.7 21.9,12.7C22.1,13.6 22,14.5 21.8,15.4L13,12.5V3.3C13.8,3.3 14.6,3.3 15.4,3.3M21.1,17.4C20,20.1 17.6,22 14.8,22.7L13,14L21.1,17.4Z",
        strategy: "M21,16.5C21,16.88 20.79,17.21 20.47,17.38L12.57,21.82C12.41,21.94 12.21,22 12,22C11.79,22 11.59,21.94 11.43,21.82L3.53,17.38C3.21,17.21 3,16.88 3,16.5V7.5C3,7.12 3.21,6.79 3.53,6.62L11.43,2.18C11.59,2.06 11.79,2 12,2C12.21,2 12.41,2.06 12.57,2.18L20.47,6.62C20.79,6.79 21,7.12 21,7.5V16.5Z",
        logo: "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4M12,6A6,6 0 0,0 6,12A6,6 0 0,0 12,18A6,6 0 0,0 18,12A6,6 0 0,0 12,6M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z"
    }

    useEffect(() => {
        const handleRouteChange = () => {
            setSidebarOpen(false)
            setSearchOpen(false)
        }
        router.events?.on('routeChangeComplete', handleRouteChange)
        return () => {
            router.events?.off('routeChangeComplete', handleRouteChange)
        }
    }, [router])

    const menuItems = [
        { name: '首頁', icon: icons.home, href: '/' },
        { name: '投資組合', icon: icons.chart, href: '/portfolio' },
        { name: '模擬交易', icon: icons.chart, href: '/trading' },
        { name: '策略開發', icon: icons.strategy, href: '/strategy' },
    ]

    return (
        <div className="min-h-screen bg-[#101827] text-gray-100 flex flex-col font-sans">
            <Head>
                <title>AlphaForge_ | 專業級台股策略鍛造平台</title>
                <meta name="description" content="AlphaForge 為投資者提供最強大的台股策略研發與回測工具，助您鍛造出高勝率的投資組合。" />
                <meta name="viewport" content="width=device-width, initial-scale=1" />
                <link rel="icon" type="image/svg+xml" href="/alphaforge/favicon.svg?v=3" />
                <link rel="shortcut icon" href="/alphaforge/favicon.svg?v=3" />
                <link rel="apple-touch-icon" href="/alphaforge/apple-touch-icon.png?v=3" />
                <meta name="apple-mobile-web-app-capable" content="yes" />
                <meta name="apple-mobile-web-app-status-bar-style" content="black-translucent" />
                <meta name="apple-mobile-web-app-title" content="AlphaForge" />
            </Head>

            <header className="bg-[#101827]/80 backdrop-blur-md sticky top-0 z-50 border-b border-zinc-800/50">
                <div className="max-w-7xl mx-auto px-4 h-16 flex justify-between items-center relative">
                    <button onClick={() => setSidebarOpen(true)} className="p-2 text-zinc-400 hover:text-emerald-400">
                        <SVGPresenter path={icons.menu} size={28} />
                    </button>

                    <div className="absolute left-1/2 -translate-x-1/2">
                        <Link href="/" className="text-xl sm:text-2xl font-bold tracking-tight flex items-center gap-2 group">
                            <SVGPresenter path={icons.logo} size={32} className="fill-emerald-400 transition-transform group-hover:scale-105" />
                            <span className="text-neutral-50 group-hover:text-emerald-400 transition-colors">AlphaForge<span className="text-emerald-400">_</span></span>
                        </Link>
                    </div>

                    <button onClick={() => setSearchOpen(true)} className="p-2 text-zinc-400 hover:text-emerald-400">
                        <SVGPresenter path={icons.magnify} size={28} />
                    </button>
                </div>
            </header>

            <aside className={`fixed inset-y-0 left-0 w-72 bg-zinc-900 z-[60] transform transition-transform duration-300 ${isSidebarOpen ? 'translate-x-0' : '-translate-x-full'}`}>
                <div className="flex flex-col h-full border-r border-zinc-800">
                    <div className="p-6 flex justify-between items-center border-b border-zinc-800">
                        <span className="font-bold text-zinc-500 uppercase text-xs tracking-widest">Menu</span>
                        <button onClick={() => setSidebarOpen(false)} className="text-zinc-500 hover:text-white">
                            <SVGPresenter path={icons.close} size={24} />
                        </button>
                    </div>
                    <nav className="flex-grow p-4 space-y-2">
                        {menuItems.map(item => (
                            <Link
                                key={item.name}
                                href={item.href}
                                className="flex items-center gap-4 px-4 py-3 rounded-lg hover:bg-emerald-500/10 hover:text-emerald-400 transition-all"
                            >
                                <SVGPresenter path={item.icon} size={24} />
                                <span className="font-bold">{item.name}</span>
                            </Link>
                        ))}
                    </nav>
                </div>
            </aside>
            {isSidebarOpen && <div className="fixed inset-0 bg-black/60 z-[55]" onClick={() => setSidebarOpen(false)} />}

            {/* Search Dropdown Overlay */}
            {isSearchOpen && (
                <div
                    className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[90] transition-opacity"
                    onClick={() => setSearchOpen(false)}
                />
            )}

            {/* Search Dropdown Menu */}
            <div className={`fixed top-0 left-0 right-0 bg-zinc-900 border-b border-zinc-800 z-[100] transform transition-transform duration-300 shadow-2xl ${isSearchOpen ? 'translate-y-0' : '-translate-y-full'}`}>
                <div className="max-w-4xl mx-auto px-4 py-6 flex flex-col gap-4">
                    <div className="flex items-center gap-4">
                        <div className="flex-1 relative">
                            <div className="absolute inset-y-0 left-4 flex items-center pointer-events-none">
                                <SVGPresenter path={icons.magnify} size={24} className="text-zinc-500" />
                            </div>
                            <input
                                ref={searchInputRef}
                                className="w-full bg-black/50 border border-zinc-700/50 rounded-xl focus:border-emerald-500 py-4 pl-12 pr-4 text-xl outline-none transition-all placeholder-zinc-600 font-mono text-zinc-100 focus:bg-zinc-900 focus:ring-1 focus:ring-emerald-500/50 shadow-inner"
                                placeholder="輸入股票代號 (例如: 2330, 2454)..."
                                value={searchInput}
                                onChange={e => setSearchInput(e.target.value)}
                                onKeyDown={e => {
                                    if (e.key === 'Enter' && searchInput.trim()) {
                                        const symbol = searchInput.trim()
                                        addSearchHistory(symbol)
                                        router.push(`/stock/${symbol}`)
                                        setSearchOpen(false)
                                    }
                                }}
                            />
                        </div>
                        <button onClick={() => setSearchOpen(false)} className="p-3 text-zinc-400 hover:text-white bg-zinc-800/50 hover:bg-zinc-700/50 rounded-xl transition-all">
                            <SVGPresenter path={icons.close} size={24} />
                        </button>
                    </div>

                    <div className="flex flex-col gap-3 mt-2">
                        <span className="text-sm font-bold text-zinc-500 tracking-widest flex items-center gap-2">
                            <SVGPresenter path={icons.strategy} size={16} />
                            {searchHistory.length > 0 ? '近期搜尋' : '熱門推介'}
                        </span>
                        <div className="flex flex-wrap gap-2">
                            {(searchHistory.length > 0 ? searchHistory : DEFAULT_HOT_SEARCHES).map((stock) => (
                                <button
                                    key={stock.symbol}
                                    onClick={() => {
                                        addSearchHistory(stock.symbol, stock.name)
                                        router.push(`/stock/${stock.symbol}`)
                                        setSearchOpen(false)
                                    }}
                                    className="px-4 py-2 bg-zinc-800/40 hover:bg-emerald-500/10 border border-zinc-700/50 hover:border-emerald-500/40 rounded-lg text-sm transition-all flex items-center gap-2 group"
                                >
                                    <span className="font-mono text-emerald-400 group-hover:text-emerald-300">{stock.symbol}</span>
                                    {stock.name && <span className="text-zinc-300 group-hover:text-white">{stock.name}</span>}
                                </button>
                            ))}
                        </div>
                    </div>
                </div>
            </div>

            <main className="flex-grow">
                {children}
            </main>

            <footer className="py-12 border-t border-zinc-900 bg-[#101827] text-zinc-700 flex flex-col items-center gap-6">
                <div className="flex items-center gap-2 opacity-50 grayscale hover:grayscale-0 transition-all duration-500">
                    <SVGPresenter path={icons.logo} size={24} className="fill-emerald-400" />
                    <span className="text-lg font-bold tracking-tighter text-zinc-400">AlphaForge_</span>
                </div>
                <p className="text-[10px] font-mono tracking-[0.2em] uppercase">
                    &copy; {new Date().getFullYear()} ALPHAFORGE PROJECT // FORGED WITH PRECISION
                </p>
            </footer>
        </div>
    )
}

export default Layout
