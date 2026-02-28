import React, { useState } from 'react';

interface Props {
    title: string;
    description: string;
}

export default function EducationalHint({ title, description }: Props) {
    const [show, setShow] = useState(false);

    return (
        <div className="relative inline-block ml-2 group"
            onMouseEnter={() => setShow(true)}
            onMouseLeave={() => setShow(false)}
            onClick={(e) => { e.preventDefault(); setShow(!show); }}
        >
            <div className="w-5 h-5 rounded-full bg-gold-500/20 text-gold-500 flex items-center justify-center text-xs font-bold cursor-help border border-gold-500/50 hover:bg-gold-500 hover:text-gray-900 transition-colors tooltip-trigger">
                ?
            </div>

            {show && (
                <div className="absolute z-50 bottom-full mb-2 left-1/2 transform -translate-x-1/2 w-64 md:w-72 p-4 bg-gray-800 border border-gray-600 rounded-xl shadow-2xl text-sm font-normal text-gray-200 pointer-events-none">
                    <div className="font-bold text-gold-400 mb-2 border-b border-gray-700 pb-1">{title}</div>
                    <div className="leading-relaxed text-gray-300">{description}</div>
                    <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1 border-4 border-transparent border-t-gray-600"></div>
                    <div className="absolute top-full left-1/2 transform -translate-x-1/2 -mt-1 h-3 w-3 rotate-45 bg-gray-800 border-b border-r border-gray-600"></div>
                </div>
            )}
        </div>
    );
}
