import React, { useState, useEffect, useRef } from 'react'
import Link from 'next/link'
import Head from 'next/head'
import { useRouter } from 'next/router'
import DailyGlossary from './DailyGlossary'

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
    const [isGlossaryOpen, setGlossaryOpen] = useState(false)
    const [searchInput, setSearchInput] = useState('')
    const searchInputRef = useRef<HTMLInputElement>(null)
    const [searchHistory, setSearchHistory] = useState<SearchHistoryItem[]>([])
    const [mounted, setMounted] = useState(false)

    useEffect(() => {
        setMounted(true)
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
        strategy: "M16,6L18.29,8.29L13.42,13.17L9.42,9.17L2,16.59L3.41,18L9.42,12L13.42,16L19.71,9.71L22,12V6H16Z",
        logo: "M12,2A10,10 0 0,0 2,12A10,10 0 0,0 12,22A10,10 0 0,0 22,12A10,10 0 0,0 12,2M12,4A8,8 0 0,1 20,12A8,8 0 0,1 12,20A8,8 0 0,1 4,12A8,8 0 0,1 12,4M12,6A6,6 0 0,0 6,12A6,6 0 0,0 12,18A6,6 0 0,0 18,12A6,6 0 0,0 12,6M12,8A4,4 0 0,1 16,12A4,4 0 0,1 12,16A4,4 0 0,1 8,12A4,4 0 0,1 12,8M12,10A2,2 0 0,0 10,12A2,2 0 0,0 12,14A2,2 0 0,0 14,12A2,2 0 0,0 12,10Z",
        book: "M21,5C19.89,4.65 18.67,4.45 17.5,4.45C15.83,4.45 14.09,4.75 12.5,5.5C10.91,4.75 9.17,4.45 7.5,4.45C6.33,4.45 5.11,4.65 4,5V18.5C5.11,18.15 6.33,17.95 7.5,17.95C9.17,17.95 10.91,18.25 12.5,19C14.09,18.25 15.83,17.95 17.5,17.95C18.67,17.95 19.89,18.15 21,18.5V5M19,16.5C18.5,16.45 18,16.45 17.5,16.45C15.91,16.45 14.39,16.75 13,17.3V7.3C14.39,6.75 15.91,6.45 17.5,6.45C18,6.45 18.5,6.45 19,6.5V16.5Z",
        ecf: "M22,21H2V3H4V19H6V10H10V19H12V14H16V19H18V7H22V21Z",
        signal: "M7,2V13H10V22L17,11H13L17,2H7Z",
        console: "M20,19V7H4V19H20M20,3A2,2 0 0,1 22,5V19A2,2 0 0,1 20,21H4A2,2 0 0,1 2,19V5C2,3.89 2.9,3 4,3H20M13,17V15H18V17H13M9.58,13L8.17,11.58L10.75,9L8.17,6.41L9.58,5L13.58,9L9.58,13Z"
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
        { name: '今日最強訊號', icon: icons.signal, href: '/signals' },
        { name: '策略開發', icon: icons.strategy, href: '/strategy' },
        { name: '系統日誌', icon: icons.console, href: '/logs' },
        // { name: 'ECF 分析', icon: icons.ecf, href: '/ecf' },
    ]

    return (
        <>
            <div className="min-h-screen bg-[#101827] text-gray-100 flex flex-col font-sans" suppressHydrationWarning>
                {mounted && (
                    <>
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

                                <div className="flex items-center gap-1">
                                    <button onClick={() => setSearchOpen(true)} className="p-2 text-zinc-400 hover:text-emerald-400 transition-colors" title="搜尋股票">
                                        <SVGPresenter path={icons.magnify} size={28} />
                                    </button>
                                </div>
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

                        {/* Overlays Container - 獨立渲染避免與外掛操作主 DOM 衝突 */}
                        <div id="layout-overlays">
                            {isSidebarOpen && (
                                <div key="sidebar-overlay" className="fixed inset-0 bg-black/60 z-[55]" onClick={() => setSidebarOpen(false)} />
                            )}

                            {isSearchOpen && (
                                <div
                                    key="search-overlay"
                                    className="fixed inset-0 bg-black/60 backdrop-blur-sm z-[90] transition-opacity"
                                    onClick={() => setSearchOpen(false)}
                                />
                            )}
                        </div>

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

                        <DailyGlossary isOpen={isGlossaryOpen} onClose={() => setGlossaryOpen(false)} />

                        <footer className="py-2.5 border-t border-zinc-900 bg-[#101827] text-zinc-400 flex flex-col sm:flex-row items-center justify-center gap-x-12 gap-y-1 px-4 transition-all">
                            <div className="flex items-center gap-2 text-zinc-400">
                                <SVGPresenter path={icons.logo} size={16} className="fill-emerald-400" />
                                <span className="text-xs font-bold tracking-tight text-white/90">AlphaForge_</span>
                            </div>
                            <p className="text-[9px] font-mono tracking-wider uppercase text-zinc-500">
                                &copy; {new Date().getFullYear()} ALPHAFORGE PROJECT // FORGED WITH PRECISION
                            </p>
                        </footer>
                    </>
                )}
            </div>
        </>
    )
}

export default Layout
