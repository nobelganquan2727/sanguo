'use client';

import { ReactNode, useState, useEffect } from 'react';

interface HoverTooltipProps {
  event: any;
  top: number;
  left?: number;
  tooltipMode: 'classical' | 'modern';
  setTooltipMode: (m: 'classical' | 'modern') => void;
  onMouseEnter: () => void;
  onMouseLeave: () => void;
  onEdit: (evt: any) => void;
  renderDesc: (text: string) => ReactNode;
}

export default function HoverTooltip({
  event, top, left, tooltipMode, setTooltipMode,
  onMouseEnter, onMouseLeave, onEdit, renderDesc,
}: HoverTooltipProps) {
  const [activeIdx, setActiveIdx] = useState<number | null>(null);

  useEffect(() => {
    setActiveIdx(null);
  }, [event]);

  const events = Array.isArray(event) ? event : (event ? [event] : []);
  if (events.length === 0 || !events[0].desc) return null;

  const isList = events.length > 1;

  return (
    <div
      className="absolute z-50 w-[420px] bg-[#0c1821]/95 backdrop-blur-md border border-[#e53e3e] rounded-md shadow-[0_0_20px_rgba(229,62,62,0.4)] p-5 max-h-[400px] overflow-y-auto"
      style={{ top, left: left !== undefined ? left : 328 }}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex flex-col gap-3">
        {events.map((evt, idx) => {
          const isActive = isList ? activeIdx === idx : true;
          return (
            <div 
              key={evt.id || idx} 
              className="border-b border-[#4a5f78]/50 pb-3 last:border-0" 
              onMouseEnter={() => isList && setActiveIdx(idx)}
            >
              {/* Header */}
              <div className="flex items-center gap-3 mb-2 cursor-pointer">
                <span className="px-2 py-0.5 bg-amber-500/20 text-amber-500 text-xs rounded border border-amber-500/50">
                  {evt.year != null ? `${evt.year}年` : '不详'}
                </span>
                <h3 className={`font-bold flex-1 leading-snug transition-colors ${isActive ? 'text-white' : 'text-slate-400'}`}>
                  {evt.title}
                </h3>
                {isActive && (
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
                )}
              </div>

              {/* Content */}
              {isActive && (
                <div className="mt-2 animate-in fade-in slide-in-from-top-2 duration-200">
                  {tooltipMode === 'classical' ? (
                    <p className="text-slate-300 text-sm leading-relaxed font-serif text-justify">
                      {evt.source_text || evt.desc}
                    </p>
                  ) : (
                    <p className="text-slate-300 text-sm leading-relaxed text-justify">
                      {renderDesc(evt.desc)}
                    </p>
                  )}
                  {/* Actions */}
                  <div className="mt-3 pt-2 border-t border-[#4a5f78]/60 flex justify-end">
                    <button
                      onClick={() => onEdit(evt)}
                      className="text-xs text-amber-500 hover:text-amber-300 border border-amber-500/40 hover:border-amber-400 px-2 py-1 rounded transition-colors flex items-center gap-1"
                    >
                      ✏️ 修正
                    </button>
                  </div>
                </div>
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
