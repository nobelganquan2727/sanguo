'use client';

import { CheckCircle, SlidersHorizontal, X, ChevronDown } from 'lucide-react';
import Slider from 'rc-slider';
import 'rc-slider/assets/index.css';
import { useRef } from 'react';

interface FilterPanelProps {
  timeRange: number[];
  setTimeRange: (v: number[]) => void;
  filterPersonInclude: string;
  setFilterPersonInclude: (v: string) => void;
  filterPersonOr: string;
  setFilterPersonOr: (v: string) => void;
  filterEventType: string;
  setFilterEventType: (v: string) => void;
  filterMeta: { event_types: string[] };
  onApply: () => void;
  onClose: () => void;
}

function FilterPanel({
  timeRange, setTimeRange,
  filterPersonInclude, setFilterPersonInclude,
  filterPersonOr, setFilterPersonOr,
  filterEventType, setFilterEventType,
  filterMeta, onApply, onClose,
}: FilterPanelProps) {
  return (
    <div className="bg-[#0c1821] border-b border-[#4a5f78] p-3 flex flex-col gap-3 text-xs pointer-events-auto">
      {/* Time range */}
      <div className="flex flex-col gap-2">
        <div className="flex items-center justify-between">
          <label className="text-slate-400 uppercase tracking-widest">时间范围</label>
          <button
            onClick={() => setTimeRange([180, 280])}
            className="text-[10px] text-amber-500 hover:text-amber-300 border border-amber-500/40 hover:border-amber-400 px-1.5 py-0.5 rounded transition-colors"
          >全部时期</button>
        </div>
        <div className="px-1">
          <Slider
            range min={180} max={280} value={timeRange}
            onChange={val => setTimeRange(val as number[])}
            allowCross={false}
            trackStyle={[{ backgroundColor: '#e53e3e', height: 3 }]}
            handleStyle={[
              { borderColor: '#fc8181', height: 14, width: 14, backgroundColor: '#c53030', opacity: 1, marginTop: -6, boxShadow: '0 0 6px rgba(229,62,62,0.8)' },
              { borderColor: '#fc8181', height: 14, width: 14, backgroundColor: '#c53030', opacity: 1, marginTop: -6, boxShadow: '0 0 6px rgba(229,62,62,0.8)' },
            ]}
            railStyle={{ backgroundColor: '#2d3f55', height: 3 }}
          />
        </div>
        <div className="flex justify-between text-slate-400 font-mono">
          <span className="text-amber-500 font-bold">{timeRange[0]}年</span>
          <span className="text-amber-500 font-bold">{timeRange[1]}年</span>
        </div>
      </div>

      {/* Person include AND */}
      <div className="flex flex-col gap-1">
        <label className="text-slate-400 uppercase tracking-widest">
          包含人物 <span className="text-slate-600 normal-case">(逗号分隔，且逻辑)</span>
        </label>
        <input
          value={filterPersonInclude}
          onChange={e => setFilterPersonInclude(e.target.value)}
          placeholder="如: 刘备,诸葛亮"
          className="bg-[#1a2f4c] border border-[#4a5f78] rounded px-2 py-1.5 text-white placeholder-slate-600 focus:outline-none focus:border-green-500"
        />
      </div>

      {/* Person include OR */}
      <div className="flex flex-col gap-1">
        <label className="text-slate-400 uppercase tracking-widest">
          包含人物 <span className="text-slate-600 normal-case">(逗号分隔，或逻辑)</span>
        </label>
        <input
          value={filterPersonOr}
          onChange={e => setFilterPersonOr(e.target.value)}
          placeholder="如: 刘备,曹操"
          className="bg-[#1a2f4c] border border-[#4a5f78] rounded px-2 py-1.5 text-white placeholder-slate-600 focus:outline-none focus:border-blue-500"
        />
      </div>

      {/* Event type */}
      <div className="flex flex-col gap-1">
        <label className="text-slate-400 uppercase tracking-widest">事件类型</label>
        <select
          value={filterEventType}
          onChange={e => setFilterEventType(e.target.value)}
          className="bg-[#1a2f4c] border border-[#4a5f78] rounded px-2 py-1.5 text-white focus:outline-none focus:border-amber-500 appearance-none"
        >
          <option value="">全部</option>
          {filterMeta.event_types.map(t => (
            <option key={t} value={t}>{t}</option>
          ))}
        </select>
      </div>

      {/* Actions */}
      <div className="flex items-center justify-between pt-1 border-t border-[#4a5f78]">
        <button
          onClick={() => { setFilterPersonInclude(''); setFilterPersonOr(''); setFilterEventType(''); setTimeRange([180, 280]); }}
          className="text-slate-500 hover:text-slate-300 text-xs transition-colors"
        >
          清除过滤
        </button>
        <button
          onClick={onApply}
          className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold text-xs px-3 py-1.5 rounded transition-colors"
        >
          <CheckCircle className="w-3.5 h-3.5" />
          应用过滤
        </button>
      </div>
    </div>
  );
}

interface EventPanelProps {
  show: boolean;
  onToggle: (v: boolean) => void;
  eventsList: any[];
  selectedEventIds: Set<string>;
  onToggleEvent: (evt: any) => void;
  onHoverEvent: (evt: any, top: number) => void;
  onLeaveEvent: () => void;
  showFilter: boolean;
  onToggleFilter: () => void;
  // filter props passthrough
  timeRange: number[];
  setTimeRange: (v: number[]) => void;
  filterPersonInclude: string;
  setFilterPersonInclude: (v: string) => void;
  filterPersonOr: string;
  setFilterPersonOr: (v: string) => void;
  filterEventType: string;
  setFilterEventType: (v: string) => void;
  filterMeta: { event_types: string[] };
  onApplyFilter: () => void;
}

export default function EventPanel({
  show, onToggle,
  eventsList, selectedEventIds, onToggleEvent, onHoverEvent, onLeaveEvent,
  showFilter, onToggleFilter,
  timeRange, setTimeRange,
  filterPersonInclude, setFilterPersonInclude,
  filterPersonOr, setFilterPersonOr,
  filterEventType, setFilterEventType,
  filterMeta, onApplyFilter,
}: EventPanelProps) {
  const wrapperRef = useRef<HTMLDivElement | null>(null);

  if (!show) {
    return (
      <button
        onClick={() => onToggle(true)}
        className="absolute left-4 top-4 z-20 flex items-center gap-1 rounded-md border border-[#4a5f78] bg-[#0a1526]/90 px-2.5 py-1.5 text-xs text-slate-200 hover:text-white hover:border-slate-400 transition-colors"
        title="展开事件列表"
      >
        <ChevronDown className="w-3.5 h-3.5 -rotate-90" />
        事件列表
      </button>
    );
  }

  return (
    <div ref={wrapperRef} className="absolute left-4 top-4 z-20 w-80 bg-[#0a1526]/95 backdrop-blur-sm border border-[#4a5f78] rounded-md overflow-visible shadow-xl flex flex-col max-h-[580px] select-none">
      {/* Header */}
      <div className="bg-gradient-to-r from-[#6b1c23] to-[#8c2a35] py-2 px-3 border-b border-[#a4424b] flex items-center justify-between">
        <h2 className="text-sm font-bold text-white tracking-widest">事件列表</h2>
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => { e.stopPropagation(); onToggleFilter(); }}
            title="过滤器"
            className={`pointer-events-auto p-1 rounded transition-colors ${showFilter ? 'bg-amber-500 text-slate-900' : 'text-slate-300 hover:text-amber-400'}`}
          >
            <SlidersHorizontal className="w-4 h-4" />
          </button>
          <button
            onClick={() => onToggle(false)}
            title="隐藏事件列表"
            className="pointer-events-auto p-1 rounded text-slate-300 hover:text-white hover:bg-slate-700/60 transition-colors"
          >
            <X className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Filter Panel */}
      {showFilter && (
        <FilterPanel
          timeRange={timeRange} setTimeRange={setTimeRange}
          filterPersonInclude={filterPersonInclude} setFilterPersonInclude={setFilterPersonInclude}
          filterPersonOr={filterPersonOr} setFilterPersonOr={setFilterPersonOr}
          filterEventType={filterEventType} setFilterEventType={setFilterEventType}
          filterMeta={filterMeta}
          onApply={onApplyFilter}
          onClose={onToggleFilter}
        />
      )}

      {/* Events list */}
      <div className="overflow-y-auto flex-1 p-3 flex flex-col gap-2 pointer-events-auto">
        {eventsList.length === 0 ? (
          <div className="text-sm text-slate-500 text-center py-10">点击右上角「过滤」设置条件后查询事件</div>
        ) : (
          eventsList.map((evt, idx) => {
            const selected = selectedEventIds.has(evt.id);
            return (
              <div
                key={idx}
                onClick={() => onToggleEvent(evt)}
                onMouseEnter={(e) => {
                  const wrapperRect = wrapperRef.current?.getBoundingClientRect();
                  if (wrapperRect) {
                    const itemRect = (e.currentTarget as HTMLDivElement).getBoundingClientRect();
                    const rawTop = itemRect.top - wrapperRect.top;
                    onHoverEvent(evt, Math.max(0, Math.min(rawTop, 360)));
                  }
                }}
                onMouseLeave={onLeaveEvent}
                className={`text-sm flex flex-col gap-1.5 p-2 rounded cursor-pointer transition-all border ${selected
                  ? 'bg-[#1a2f4c] border-amber-500/70 shadow-[0_0_8px_rgba(245,158,11,0.25)]'
                  : 'border-transparent hover:bg-[#1a2f4c] hover:border-[#4a5f78]'
                }`}
              >
                <div className="flex items-start gap-2">
                  <div className={`mt-0.5 w-3.5 h-3.5 rounded shrink-0 border transition-colors ${selected ? 'bg-amber-500 border-amber-400' : 'bg-transparent border-slate-600'}`} />
                  <span className="font-bold text-amber-500 min-w-[42px] shrink-0">{evt.year != null ? `${evt.year}年` : '不详'}</span>
                  <span className={`font-semibold leading-tight ${selected ? 'text-amber-200' : 'text-white'}`}>{evt.title}</span>
                </div>
                {evt.type && <span className="ml-[68px] text-[10px] text-slate-500 bg-slate-800/50 px-1.5 py-0.5 rounded self-start">{evt.type}</span>}
                {evt.locations?.length > 0 && (
                  <div className="flex flex-wrap gap-1 ml-[68px]">
                    {evt.locations.map((l: string, i: number) => (
                      <span key={i} className="text-xs text-slate-400 bg-slate-800/60 px-1.5 py-0.5 rounded">📍 {l}</span>
                    ))}
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
    </div>
  );
}
