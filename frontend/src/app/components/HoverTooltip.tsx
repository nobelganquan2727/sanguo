'use client';

import { ReactNode } from 'react';

interface HoverTooltipProps {
  event: any;
  top: number;
  tooltipMode: 'classical' | 'modern';
  setTooltipMode: (m: 'classical' | 'modern') => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onEdit: () => void;
  renderDesc: (text: string) => ReactNode;
}

export default function HoverTooltip({
  event, top, tooltipMode, setTooltipMode,
  onMouseEnter, onMouseLeave, onEdit, renderDesc,
}: HoverTooltipProps) {
  if (!event?.desc) return null;

  return (
    <div
      className="absolute left-[328px] z-50 w-[420px] bg-[#0c1821]/95 backdrop-blur-md border border-[#e53e3e] rounded-md shadow-[0_0_20px_rgba(229,62,62,0.4)] p-5"
      style={{ top }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* Header */}
      <div className="flex items-center gap-3 mb-3 border-b border-[#4a5f78] pb-2">
        <span className="px-2 py-0.5 bg-amber-500/20 text-amber-500 text-xs rounded border border-amber-500/50">
          {event.year != null ? `${event.year}年` : '不详'}
        </span>
        <h3 className="text-white font-bold flex-1 leading-snug">{event.title}</h3>
        <div className="flex rounded overflow-hidden border border-[#4a5f78] shrink-0 text-[10px] font-bold">
          <button
            onClick={() => setTooltipMode('modern')}
            className={`px-2 py-1 transition-colors ${tooltipMode === 'modern' ? 'bg-amber-500 text-slate-900' : 'text-slate-400 hover:text-white'}`}
          >白话</button>
          <button
            onClick={() => setTooltipMode('classical')}
            className={`px-2 py-1 transition-colors ${tooltipMode === 'classical' ? 'bg-amber-500 text-slate-900' : 'text-slate-400 hover:text-white'}`}
          >文言</button>
        </div>
      </div>

      {/* Content */}
      {tooltipMode === 'classical' ? (
        <p className="text-slate-300 text-sm leading-relaxed font-serif text-justify">
          {event.source_text || event.desc}
        </p>
      ) : (
        <p className="text-slate-300 text-sm leading-relaxed text-justify">
          {renderDesc(event.desc)}
        </p>
      )}

      {/* Actions */}
      <div className="mt-3 pt-2 border-t border-[#4a5f78] flex justify-end">
        <button
          onClick={onEdit}
          className="text-xs text-amber-500 hover:text-amber-300 border border-amber-500/40 hover:border-amber-400 px-2 py-1 rounded transition-colors flex items-center gap-1"
        >
          ✏️ 修正
        </button>
      </div>
    </div>
  );
}
