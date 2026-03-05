import React, { useState, useEffect } from 'react';
import {
    useFloating,
    autoUpdate,
    offset,
    flip,
    shift,
    useHover,
    useFocus,
    useDismiss,
    useRole,
    useInteractions,
    FloatingPortal
} from '@floating-ui/react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import remarkMath from 'remark-math';
import rehypeKatex from 'rehype-katex';
import rehypeRaw from 'rehype-raw';
import api from '../lib/api';

interface Props {
    /** glossary.json 中的 entry id，例如 "kd-indicator" */
    glossaryId: string;
}

// 快取
const glossaryCache: Record<string, string> = {};

export default function EducationalHint({ glossaryId }: Props) {
    const [isOpen, setIsOpen] = useState(false);
    const [content, setContent] = useState('');
    const [loaded, setLoaded] = useState(false);

    const { refs, floatingStyles, context } = useFloating({
        open: isOpen,
        onOpenChange: setIsOpen,
        placement: 'top',
        middleware: [
            offset(8),
            flip({ fallbackAxisSideDirection: 'start' }),
            shift({ padding: 12 })
        ],
        whileElementsMounted: autoUpdate,
    });

    const hover = useHover(context, { move: false });
    const focus = useFocus(context);
    const dismiss = useDismiss(context);
    const role = useRole(context, { role: 'tooltip' });

    const { getReferenceProps, getFloatingProps } = useInteractions([
        hover,
        focus,
        dismiss,
        role,
    ]);

    useEffect(() => {
        if (!isOpen || loaded) return;

        if (glossaryCache[glossaryId]) {
            setContent(glossaryCache[glossaryId]);
            setLoaded(true);
            return;
        }

        const fetchGlossary = async () => {
            try {
                const res = await api.get(`/glossary/${glossaryId}`);
                glossaryCache[glossaryId] = res.data.content;
                setContent(res.data.content);
            } catch (e) {
                setContent('⚠️ 無法取得名詞解釋');
            }
            setLoaded(true);
        };
        fetchGlossary();
    }, [isOpen, loaded, glossaryId]);

    return (
        <div className="inline-block align-middle">
            <div
                ref={refs.setReference}
                {...getReferenceProps()}
                className="w-5 h-5 rounded-full bg-gold-500/20 text-gold-500 flex items-center justify-center text-xs font-bold cursor-help border border-gold-500/50 hover:bg-gold-500 hover:text-gray-900 transition-colors tooltip-trigger shadow-lg shadow-gold-500/10"
                onClick={(e) => { e.preventDefault(); setIsOpen(!isOpen); }}
            >
                ?
            </div>

            {isOpen && (
                <FloatingPortal>
                    <div
                        ref={refs.setFloating}
                        style={{ ...floatingStyles, zIndex: 99999 }}
                        {...getFloatingProps()}
                        // 移除固定寬度，改為 max-w-sm 讓內容自行決定大小
                        className="w-auto max-w-[85vw] sm:max-w-sm md:max-w-md max-h-96 overflow-y-auto p-4 sm:p-5 bg-gray-800/95 backdrop-blur-md border border-gray-600 rounded-xl shadow-2xl text-sm font-normal text-gray-200 pointer-events-auto"
                    >
                        {!loaded ? (
                            <div className="text-gray-500 animate-pulse">載入中...</div>
                        ) : (
                            <div className="prose prose-invert prose-sm max-w-none">
                                <ReactMarkdown
                                    remarkPlugins={[remarkGfm, remarkMath]}
                                    rehypePlugins={[rehypeKatex, rehypeRaw]}
                                    components={{
                                        // 客製化 markdown 元素樣式，適配深色主題
                                        h2: ({ node, ...props }) => <h2 className="text-gold-400 mt-0 mb-3 text-lg font-bold pb-2 border-b border-gray-700" {...props} />,
                                        h3: ({ node, ...props }) => <h3 className="text-gold-400 mt-0 mb-3 text-base font-bold pb-1 border-b border-gray-700" {...props} />,
                                        h4: ({ node, ...props }) => <h4 className="text-emerald-400 mt-4 mb-2 text-sm font-bold" {...props} />,
                                        p: ({ node, ...props }) => <p className="leading-relaxed mb-3 text-gray-300" {...props} />,
                                        ul: ({ node, ...props }) => <ul className="list-disc pl-5 mb-3 text-gray-300 space-y-1" {...props} />,
                                        ol: ({ node, ...props }) => <ol className="list-decimal pl-5 mb-3 text-gray-300 space-y-1" {...props} />,
                                        li: ({ node, ...props }) => <li className="marker:text-gray-500" {...props} />,
                                        // 僅保留粗體關鍵字，移除強制修改斜體與程式碼區塊顏色的設定
                                        strong: ({ node, ...props }) => <strong className="font-bold text-gold-400" {...props} />, // 亮金: 關鍵字
                                        code: ({ node, className, ...props }: any) => {
                                            const match = /language-(\w+)/.exec(className || '');
                                            return !match ? (
                                                <code className="bg-gray-700 px-1.5 py-0.5 rounded text-[0.9em] before:content-none after:content-none mx-0.5" {...props} />
                                            ) : (
                                                <code className="block bg-gray-900 p-3 rounded-lg overflow-x-auto text-sm my-2" {...props} />
                                            );
                                        },
                                    }}
                                >
                                    {content
                                        .replace(/\+\+(.*?)\+\+/g, '<span class="text-emerald-400 font-bold">$1</span>')
                                        .replace(/--(.*?)--/g, '<span class="text-rose-400 font-bold">$1</span>')}
                                </ReactMarkdown>
                            </div>
                        )}
                    </div>
                </FloatingPortal>
            )}
        </div>
    );
}
