'use client';

import React, { useState, useEffect, useRef, useCallback } from 'react';
import MapGL from 'react-map-gl/maplibre';
import DeckGL from '@deck.gl/react';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import 'maplibre-gl/dist/maplibre-gl.css';
import { CheckCircle, SlidersHorizontal, X, ChevronDown } from 'lucide-react';
import Slider from 'rc-slider';
import 'rc-slider/assets/index.css';

const INITIAL_VIEW_STATE = { longitude: 108.5, latitude: 34.0, zoom: 4.2, pitch: 0, bearing: 0 };
const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-nolabels-gl-style/style.json';

// ─── Draggable wrapper ─────────────────────────────────────────────────────────
function Draggable({ children, initialPos }: { children: React.ReactNode; initialPos: { x: number; y: number } }) {
  const [pos, setPos] = useState(initialPos);
  const dragging = useRef(false);
  const start = useRef({ mx: 0, my: 0, px: 0, py: 0 });

  const onMouseDown = (e: React.MouseEvent) => {
    // only drag via header (data-drag="true")
    if (!(e.target as HTMLElement).closest('[data-drag="true"]')) return;
    dragging.current = true;
    start.current = { mx: e.clientX, my: e.clientY, px: pos.x, py: pos.y };
    e.preventDefault();
  };

  useEffect(() => {
    const onMove = (e: MouseEvent) => {
      if (!dragging.current) return;
      setPos({ x: start.current.px + e.clientX - start.current.mx, y: start.current.py + e.clientY - start.current.my });
    };
    const onUp = () => { dragging.current = false; };
    window.addEventListener('mousemove', onMove);
    window.addEventListener('mouseup', onUp);
    return () => { window.removeEventListener('mousemove', onMove); window.removeEventListener('mouseup', onUp); };
  }, []);

  return (
    <div
      style={{ position: 'absolute', left: pos.x, top: pos.y, zIndex: 20 }}
      onMouseDown={onMouseDown}
    >
      {children}
    </div>
  );
}

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';

// ─── Main page ─────────────────────────────────────────────────────────────────
export default function Home() {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE);
  const [timeRange, setTimeRange] = useState([190, 195]);
  const [geoData, setGeoData] = useState<any[]>([]);
  const [eventsList, setEventsList] = useState<any[]>([]);

  // Selection & hover
  const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set());
  const [highlightedLocNames, setHighlightedLocNames] = useState<Set<string>>(new Set());
  const [hoveredEvent, setHoveredEvent] = useState<any>(null);

  // Filter panel
  const [showFilter, setShowFilter] = useState(false);
  const [filterMeta, setFilterMeta] = useState<{ locations: string[]; event_types: string[] }>({ locations: [], event_types: [] });
  const [filterPersonInclude, setFilterPersonInclude] = useState('');
  const [filterPersonOr, setFilterPersonOr] = useState('');
  const [filterEventType, setFilterEventType] = useState('');

  // Agent chat
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState<{ role: string; content: string }[]>([
    { role: 'ai', content: '主公，臣已就绪。可通过图谱调取各方势力的绝密卷宗。点击地图上的地名即可查阅该地史料。' },
  ]);
  const [isLoading, setIsLoading] = useState(false);

  // Person names for linkification + person timeline
  const [allPersons, setAllPersons] = useState<string[]>([]);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  // Tooltip 白话文/文言文切换
  const [tooltipMode, setTooltipMode] = useState<'classical' | 'modern'>('classical');

  useEffect(() => {
    fetch('/geo.json').then(r => r.json()).then(data => {
      const uniqueLocs = new Map();
      Object.values(data).flat().forEach((loc: any) => {
        if (loc.lat && loc.lng) uniqueLocs.set(loc.std_name, loc);
      });
      setGeoData(Array.from(uniqueLocs.values()));
    });

    // Load filter metadata on mount
    fetch(`${API_BASE}/api/filter-meta`).then(r => r.json()).then(setFilterMeta).catch(() => { });

    // Load all person names for text linkification (longest first for regex priority)
    fetch(`${API_BASE}/api/persons`).then(r => r.json()).then((d: any) => {
      const sorted = [...(d.persons || [])].sort((a: string, b: string) => b.length - a.length);
      setAllPersons(sorted);
    }).catch(() => { });

    // Auto-load default events on mount
    fetch(`${API_BASE}/api/events?start=190&end=195`).then(r => r.json()).then((d: any) => {
      setEventsList(d.events || []);
    }).catch(() => { });
  }, []);

  const sendMessage = async (query: string) => {
    if (!query.trim() || isLoading) return;
    const newHistory = [...chatHistory, { role: 'user', content: query }];
    setChatHistory(newHistory);
    setChatInput('');
    setIsLoading(true);
    try {
      const res = await fetch(`${API_BASE}/api/ask`, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: query }),
      });
      const data = await res.json();
      setChatHistory([...newHistory, { role: 'ai', content: data.answer }]);
    } catch {
      setChatHistory([...newHistory, { role: 'ai', content: '抱歉主公，臣未能联系上后台图谱引擎。请确认已运行 `python3 server.py`。' }]);
    } finally { setIsLoading(false); }
  };

  // Linkify person names in text — returns JSX with clickable spans
  const linkifyText = (text: string) => {
    if (!text || allPersons.length === 0) return <>{text}</>;
    const escaped = allPersons.map(p => p.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'g');
    const parts = text.split(regex);
    return <>{parts.map((part, i) =>
      allPersons.includes(part)
        ? <span key={i} className="text-amber-400 font-semibold">{part}</span>
        : <React.Fragment key={i}>{part}</React.Fragment>
    )}</>;
  };

  const fetchEvents = async () => {
    const params = new URLSearchParams({
      start: String(timeRange[0]), end: String(timeRange[1]),
      ...(filterPersonInclude && { person_include: filterPersonInclude }),
      ...(filterPersonOr && { person_or: filterPersonOr }),
      ...(filterEventType && { event_type: filterEventType }),
    });
    try {
      const res = await fetch(`${API_BASE}/api/events?${params}`);
      const data = await res.json();
      setEventsList(data.events || []);
      setSelectedEventIds(new Set());
      setHighlightedLocNames(new Set());
    } catch (err) { console.error(err); }
  };

  // Agent 人名点击：在事件列表里返回该人物的所有历史事件
  const loadPersonEvents = async (name: string) => {
    const params = new URLSearchParams({ start: '180', end: '280', person_include: name });
    try {
      const res = await fetch(`${API_BASE}/api/events?${params}`);
      const data = await res.json();
      setEventsList(data.events || []);
      setSelectedEventIds(new Set());
      setHighlightedLocNames(new Set());
      setFilterPersonInclude(name);
    } catch (err) { console.error(err); }
  };

  // Agent 地名点击：飞向地图对应位置，并聚焦显示
  const jumpToLocation = (locName: string) => {
    const target = geoData.find((d: any) => locName.includes(d.std_name) || d.std_name.includes(locName));
    if (target) {
      setHighlightedLocNames(new Set([target.std_name]));
      setViewState((vs: any) => ({
        ...vs, longitude: target.lng, latitude: target.lat, zoom: 6.5, transitionDuration: 1200
      }));
    }
  };

  // 对 Agent 回复做人名+地名标注
  const allLocationNames = geoData.map((d: any) => d.std_name).filter(Boolean);
  const linkifyChatText = (text: string) => {
    if (!text) return <>{text}</>;
    const tokens: { word: string; type: 'person' | 'location' | 'text' }[] = [];
    // Build combined list: persons (amber) + locations (cyan), longest first to avoid partial match
    const allTerms = [
      ...allPersons.map(w => ({ w, t: 'person' as const })),
      ...allLocationNames.map(w => ({ w, t: 'location' as const })),
    ].sort((a, b) => b.w.length - a.w.length);
    if (allTerms.length === 0) return <>{text}</>;
    const escaped = allTerms.map(({ w }) => w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&'));
    const regex = new RegExp(`(${escaped.join('|')})`, 'g');
    const parts = text.split(regex);
    return <>{parts.map((part, i) => {
      const match = allTerms.find(({ w }) => w === part);
      if (!match) return <React.Fragment key={i}>{part}</React.Fragment>;
      if (match.t === 'person') {
        return <span key={i} onClick={() => loadPersonEvents(part)} className="text-amber-400 underline cursor-pointer hover:text-amber-200 font-semibold transition-colors" title={`查看${part}的事件`}>{part}</span>;
      }
      return <span key={i} onClick={() => jumpToLocation(part)} className="text-cyan-400 underline cursor-pointer hover:text-cyan-200 font-semibold transition-colors" title={`跳转到${part}`}>{part}</span>;
    })}</>;
  };

  const toggleEvent = (evt: any) => {
    const newSelected = new Set(selectedEventIds);
    newSelected.has(evt.id) ? newSelected.delete(evt.id) : newSelected.add(evt.id);
    setSelectedEventIds(newSelected);

    const allLocs = new Set<string>();
    let firstTarget: any = null;
    eventsList.forEach(e => {
      if (newSelected.has(e.id) && e.locations?.length) {
        e.locations.forEach((l: string) => { if (l) allLocs.add(l); });
        if (!firstTarget) {
          firstTarget = geoData.find(d => e.locations.some((l: string) => l && (l.includes(d.std_name) || d.std_name.includes(l))));
        }
      }
    });
    setHighlightedLocNames(allLocs);
    if (firstTarget && newSelected.size > 0) {
      setViewState((vs: any) => ({ ...vs, longitude: firstTarget.lng, latitude: firstTarget.lat, zoom: 6.0, transitionDuration: 1200 }));
    }
  };

  // ── LOD & dedup ────────────────────────────────────────────────────────────
  const isHL = useCallback((name: string) =>
    [...highlightedLocNames].some(l => l && (l.includes(name) || name.includes(l))), [highlightedLocNames]);

  const hasSelection = highlightedLocNames.size > 0;
  const visibleData: any[] = [];
  const overlapThreshold = 1.5 / viewState.zoom;

  const sortedGeo = [...geoData].sort((a, b) => {
    const aHL = isHL(a.std_name || '');
    const bHL = isHL(b.std_name || '');
    return (bHL ? 1 : 0) - (aHL ? 1 : 0); // highlighted first
  });

  for (const d of sortedGeo) {
    const name = d.std_name || '';
    const highlighted = isHL(name);
    let shouldShow = false;

    if (hasSelection) {
      shouldShow = highlighted || name.endsWith('州') || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
    } else {
      // 无事件选中时：最多显示到郡/国级别，不触发全郡县展示
      if (viewState.zoom >= 5.0) {
        shouldShow = name.endsWith('州') || name.endsWith('郡') || name.endsWith('国') ||
          ['洛阳', '长安', '邺城', '建业', '许昌', '成都', '襄阳', '江陵', '汉中', '宛城'].includes(name);
      } else {
        shouldShow = name.endsWith('州') || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
      }
    }

    if (!shouldShow) continue;
    // 所有点（含高亮点）都做重叠检测，高亮点因为排在前面所以优先占位
    const overlap = visibleData.some(v => Math.abs(v.lng - d.lng) < overlapThreshold && Math.abs(v.lat - d.lat) < overlapThreshold);
    if (!overlap) visibleData.push(d);
  }

  const layers = [
    new ScatterplotLayer({
      id: 'cities-layer',
      data: visibleData,
      getPosition: (d: any) => [d.lng, d.lat],
      getFillColor: (d: any) => isHL(d.std_name) ? [252, 211, 77, 255] : [185, 28, 28, 200],
      getRadius: (d: any) => isHL(d.std_name) ? 22000 : 10000,
      radiusMinPixels: 4, radiusMaxPixels: 14,
      pickable: true,
      updateTriggers: { getFillColor: [highlightedLocNames], getRadius: [highlightedLocNames] },
      // 点击地图据点：仅高亮，不触发Agent查询
      onClick: () => { },
    }),
    new TextLayer({
      id: 'cities-text-layer',
      data: visibleData,
      getPosition: (d: any) => [d.lng, d.lat],
      getText: (d: any) => d.std_name,
      getSize: (d: any) => isHL(d.std_name) ? 18 : 14,
      getColor: (d: any) => isHL(d.std_name) ? [245, 158, 11, 255] : [41, 37, 36, 255],
      getAlignmentBaseline: 'bottom', getPixelOffset: [0, -10],
      fontFamily: 'Noto Serif SC, serif', fontWeight: 'bold', characterSet: 'auto',
      updateTriggers: { getSize: [highlightedLocNames], getColor: [highlightedLocNames] },
    }),
  ];

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#041527] font-sans p-6 flex items-center justify-center">
      <div className="relative w-full h-full border-2 border-[#5c6e83] rounded-lg overflow-hidden shadow-[0_0_30px_rgba(0,0,0,0.8)] bg-[#d2cdbe]">

        {/* Map */}
        <div className="absolute inset-0 z-0 opacity-90 mix-blend-multiply">
          <DeckGL viewState={viewState} onViewStateChange={({ viewState }) => setViewState(viewState)} controller={true} layers={layers}>
            <MapGL mapStyle={MAP_STYLE} />
          </DeckGL>
        </div>

        {/* Title */}
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
          <div className="px-16 py-3 bg-gradient-to-b from-[#1a2f4c] to-[#0a1628] border border-[#4a5f78] rounded-md shadow-lg flex items-center gap-6">
            <div className="h-px w-12 bg-gradient-to-r from-transparent to-[#4a5f78]" />
            <h1 className="text-2xl font-bold text-white tracking-[0.2em] font-serif" style={{ textShadow: '0 2px 4px rgba(0,0,0,0.8)' }}>三国历史数字地图系统</h1>
            <div className="h-px w-12 bg-gradient-to-l from-transparent to-[#4a5f78]" />
          </div>
        </div>

        {/* ── Draggable Event List ──────────────────────────────────────────── */}
        <Draggable initialPos={{ x: 32, y: 96 }}>
          <div className="w-80 bg-[#0a1526]/95 backdrop-blur-sm border border-[#4a5f78] rounded-md overflow-visible shadow-xl flex flex-col max-h-[580px] select-none">

            {/* Header (drag handle) */}
            <div data-drag="true" className="bg-gradient-to-r from-[#6b1c23] to-[#8c2a35] py-2 px-3 border-b border-[#a4424b] flex items-center justify-between cursor-grab active:cursor-grabbing">
              <h2 className="text-sm font-bold text-white tracking-widest">事件列表</h2>
              <button
                data-drag="false"
                onClick={(e) => { e.stopPropagation(); setShowFilter(v => !v); }}
                title="过滤器"
                className={`pointer-events-auto p-1 rounded transition-colors ${showFilter ? 'bg-amber-500 text-slate-900' : 'text-slate-300 hover:text-amber-400'}`}
              >
                <SlidersHorizontal className="w-4 h-4" />
              </button>
            </div>

            {/* Filter Panel */}
            {showFilter && (
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
                  <label className="text-slate-400 uppercase tracking-widest">包含人物 <span className="text-slate-600 normal-case">(逗号分隔，且逻辑)</span></label>
                  <input
                    value={filterPersonInclude}
                    onChange={e => setFilterPersonInclude(e.target.value)}
                    placeholder="如: 刘备,诸葛亮"
                    className="bg-[#1a2f4c] border border-[#4a5f78] rounded px-2 py-1.5 text-white placeholder-slate-600 focus:outline-none focus:border-green-500"
                  />
                </div>

                {/* Person include OR */}
                <div className="flex flex-col gap-1">
                  <label className="text-slate-400 uppercase tracking-widest">包含人物 <span className="text-slate-600 normal-case">(逗号分隔，或逻辑)</span></label>
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
                    onClick={() => { fetchEvents(); setShowFilter(false); }}
                    className="flex items-center gap-1.5 bg-amber-500 hover:bg-amber-400 text-slate-900 font-bold text-xs px-3 py-1.5 rounded transition-colors"
                  >
                    <CheckCircle className="w-3.5 h-3.5" />
                    应用过滤
                  </button>
                </div>
              </div>
            )}

            {/* Events */}
            <div className="overflow-y-auto flex-1 p-3 flex flex-col gap-2 pointer-events-auto">
              {eventsList.length === 0 ? (
                <div className="text-sm text-slate-500 text-center py-10">点击右上角「过滤」设置条件后查询事件</div>
              ) : (
                eventsList.map((evt, idx) => {
                  const selected = selectedEventIds.has(evt.id);
                  return (
                    <div
                      key={idx}
                      onClick={() => toggleEvent(evt)}
                      onMouseEnter={() => {
                        if (hideTimer.current) clearTimeout(hideTimer.current);
                        setHoveredEvent(evt);
                      }}
                      onMouseLeave={() => {
                        hideTimer.current = setTimeout(() => setHoveredEvent(null), 200);
                      }}
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

          {/* Hover tooltip — rendered outside list scroll */}
          {hoveredEvent?.desc && (
            <div
              className="absolute left-[328px] top-0 z-50 w-[420px] bg-[#0c1821]/95 backdrop-blur-md border border-[#e53e3e] rounded-md shadow-[0_0_20px_rgba(229,62,62,0.4)] p-5"
              onMouseEnter={() => { if (hideTimer.current) clearTimeout(hideTimer.current); }}
              onMouseLeave={() => { hideTimer.current = setTimeout(() => setHoveredEvent(null), 100); }}
            >
              {/* Header */}
              <div className="flex items-center gap-3 mb-3 border-b border-[#4a5f78] pb-2">
                <span className="px-2 py-0.5 bg-amber-500/20 text-amber-500 text-xs rounded border border-amber-500/50">{hoveredEvent.year != null ? `${hoveredEvent.year}年` : '不详'}</span>
                <h3 className="text-white font-bold flex-1 leading-snug">{hoveredEvent.title}</h3>
                {/* Mode toggle */}
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
                  {hoveredEvent.source_text || hoveredEvent.desc}
                </p>
              ) : (
                <p className="text-slate-300 text-sm leading-relaxed text-justify">{linkifyText(hoveredEvent.desc)}</p>
              )}
            </div>
          )}
        </Draggable>

        {/* ── Agent Panel (right, draggable) ────────────────────────────────── */}
        <Draggable initialPos={{ x: 900, y: 96 }}>
          <div className="w-[340px] bg-[#0a1526]/95 backdrop-blur-sm border border-[#4a5f78] rounded-md shadow-xl flex flex-col max-h-[580px] select-none">
            <div data-drag="true" className="bg-gradient-to-r from-[#6b1c23] to-[#8c2a35] py-2 border-b border-[#a4424b] px-4 flex justify-between items-center cursor-grab active:cursor-grabbing">
              <h2 className="text-sm font-bold text-white tracking-widest">幕僚</h2>
              <div className="flex items-center gap-2">
                <span className="text-[10px] text-green-400 font-mono">Neo4j</span>
                <div className="w-2 h-2 rounded-full bg-green-500 shadow-[0_0_8px_#22c55e]" />
              </div>
            </div>
            <div className="flex-1 overflow-y-auto p-4 flex flex-col gap-3 pointer-events-auto">
              {chatHistory.map((msg, i) => (
                <div key={i} className={`flex ${msg.role === 'user' ? 'justify-end' : 'justify-start'}`}>
                  <div className={`p-3 rounded-md text-sm max-w-[85%] leading-relaxed ${msg.role === 'user'
                    ? 'bg-[#8c2a35] text-white border border-[#a4424b]'
                    : 'bg-[#1a2f4c] border border-[#4a5f78] text-slate-300'}`}>
                    {msg.role === 'ai' ? linkifyChatText(msg.content) : msg.content}
                  </div>
                </div>
              ))}
              {isLoading && (
                <div className="flex justify-start">
                  <div className="bg-[#1a2f4c] border border-[#4a5f78] p-3 rounded-md text-sm text-slate-400 flex items-center gap-2">
                    {[0, 0.1, 0.2].map((d, i) => <div key={i} className="w-1.5 h-1.5 bg-amber-500 rounded-full animate-bounce" style={{ animationDelay: `${d}s` }} />)}
                    <span className="ml-1">臣正在翻阅史料卷宗...</span>
                  </div>
                </div>
              )}
            </div>
            <div className="p-3 border-t border-[#4a5f78] bg-[#0c1821] pointer-events-auto">
              <input
                type="text" value={chatInput}
                onChange={e => setChatInput(e.target.value)}
                onKeyDown={e => e.key === 'Enter' && sendMessage(chatInput)}
                placeholder="向幕僚提问..."
                className="w-full bg-[#1a2f4c] border border-[#4a5f78] rounded py-2 px-3 text-sm focus:outline-none focus:border-[#e53e3e] text-white placeholder-slate-500"
              />
            </div>
          </div>
        </Draggable>

      </div>
    </div>
  );
}
