import React, { useState } from 'react';
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

interface Props {
    title: string;
    description: string;
}

export default function EducationalHint({ title, description }: Props) {
    const [isOpen, setIsOpen] = useState(false);

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

    return (
        <div className="inline-block ml-2 align-middle">
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
                        className="w-64 md:w-72 p-4 bg-gray-800/95 backdrop-blur-md border border-gray-600 rounded-xl shadow-2xl text-sm font-normal text-gray-200 pointer-events-none"
                    >
                        <div className="font-bold text-gold-400 mb-2 border-b border-gray-700 pb-1">{title}</div>
                        <div className="leading-relaxed text-gray-300">{description}</div>
                    </div>
                </FloatingPortal>
            )}
        </div>
    );
}
