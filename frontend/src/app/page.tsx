'use client';

import { useState, useRef, useEffect } from 'react';
import { useMapData } from './hooks/useMapData';
import { useLinkify } from './hooks/useLinkify';
import MapView from './components/MapView';
import EventPanel from './components/EventPanel';
import HoverTooltip from './components/HoverTooltip';
import AgentPanel from './components/AgentPanel';
import EditModal from './components/EditModal';
import PersonRelationsModal from './components/PersonRelationsModal';
import TimelineSlider from './components/TimelineSlider';
import { locationMatchesGeoName } from './utils/locationMatch';
import { Calendar } from 'lucide-react';

const INITIAL_VIEW_STATE = { longitude: 108.5, latitude: 34.0, zoom: 4.2, pitch: 0, bearing: 0 };
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';
const EVENT_PAGE_SIZE = 100;
console.log('API_BASE:', API_BASE, process.env.NEXT_PUBLIC_API_BASE);

export default function Home() {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE);
  const [timeRange, setTimeRange] = useState([190, 195]);
  const [timelineYear, setTimelineYear] = useState(190);
  const [showTimeline, setShowTimeline] = useState(true);
  const [isPortraitMobile, setIsPortraitMobile] = useState(false);

  useEffect(() => {
    const checkOrientation = () => {
      const isMobileDevice = /Mobi|Android|iPhone|iPad/i.test(navigator.userAgent) || (window.innerWidth < 768);
      const isPortrait = window.innerHeight > window.innerWidth;
      setIsPortraitMobile(!!(isMobileDevice && isPortrait));
    };

    checkOrientation();
    window.addEventListener('resize', checkOrientation);
    window.addEventListener('orientationchange', checkOrientation);
    return () => {
      window.removeEventListener('resize', checkOrientation);
      window.removeEventListener('orientationchange', checkOrientation);
    };
  }, []);

  // Selection & hover
  const [selectedEventIds, setSelectedEventIds] = useState<Set<string>>(new Set());
  const [highlightedLocNames, setHighlightedLocNames] = useState<Set<string>>(new Set());
  const [hoveredEvent, setHoveredEvent] = useState<any>(null);
  const [hoverTooltipTop, setHoverTooltipTop] = useState(0);
  const [hoverTooltipLeft, setHoverTooltipLeft] = useState<number | undefined>(undefined);
  const hideTimer = useRef<ReturnType<typeof setTimeout> | null>(null);

  // Filter panel
  const [showFilter, setShowFilter] = useState(false);
  const [showEventPanel, setShowEventPanel] = useState(false);
  const [filterPersonInclude, setFilterPersonInclude] = useState('');
  const [filterPersonOr, setFilterPersonOr] = useState('');
  const [filterEventType, setFilterEventType] = useState('');
  const [eventQueryParams, setEventQueryParams] = useState<URLSearchParams>(() => new URLSearchParams({ start: '190', end: '195' }));
  const [eventOffset, setEventOffset] = useState(EVENT_PAGE_SIZE);
  const [eventsHasMore, setEventsHasMore] = useState(true);
  const [eventsLoadingMore, setEventsLoadingMore] = useState(false);

  // Agent chat
  const [showAgentPanel, setShowAgentPanel] = useState(true);
  const [chatInput, setChatInput] = useState('');
  const [chatHistory, setChatHistory] = useState<{ role: string; content: string }[]>([
    { role: 'ai', content: '主公，臣已就绪。可通过图谱调取各方势力的绝密卷宗。点击地图上的地名即可查阅该地史料。' },
  ]);
  const [isLoading, setIsLoading] = useState(false);

  // Tooltip mode
  const [tooltipMode, setTooltipMode] = useState<'classical' | 'modern'>('modern');

  // Edit modal
  const [editModalOpen, setEditModalOpen] = useState(false);
  const [editTarget, setEditTarget] = useState<any>(null);
  const [editField, setEditField] = useState<'locations' | 'std_start_year'>('locations');
  const [editValue, setEditValue] = useState('');

  // Person relations modal
  const [relationsModalOpen, setRelationsModalOpen] = useState(false);
  const [relationsPerson, setRelationsPerson] = useState('');
  const [personRelations, setPersonRelations] = useState<any>(null);
  const [relationsLoading, setRelationsLoading] = useState(false);

  const {
    geoData,
    eventsList,
    setEventsList,
    filterMeta,
    allPersons,
    fetchEventsPage,
    fetchLocationEvents,
    fetchPersonRelations,
    fetchEventDetail,
    sendMessage,
    submitFeedback,
  } = useMapData();
  const allLocationNames = geoData.map((d: any) => d.std_name).filter(Boolean);

  const replaceEvents = async (params: URLSearchParams) => {
    const { events, hasMore } = await fetchEventsPage(params, 0, EVENT_PAGE_SIZE);
    setEventsList(events);
    setEventQueryParams(new URLSearchParams(params));
    setEventOffset(events.length);
    setEventsHasMore(hasMore);
    setSelectedEventIds(new Set());
    setHighlightedLocNames(new Set());
  };

  const loadPersonEvents = async (name: string) => {
    const params = new URLSearchParams({ start: '180', end: '280', person_include: name });
    await replaceEvents(params);
    setFilterPersonInclude(name);
  };

  const handlePersonClick = async (name: string) => {
    setRelationsPerson(name);
    setRelationsModalOpen(true);
    setRelationsLoading(true);
    setPersonRelations(null);
    await loadPersonEvents(name);
    const relationsData = await fetchPersonRelations(name);
    setPersonRelations(relationsData);
    setRelationsLoading(false);
  };

  const jumpToLocation = (locName: string) => {
    const target = geoData.find((d: any) => locationMatchesGeoName(locName, d));
    if (target) {
      setHighlightedLocNames(new Set([target.std_name]));
      setViewState((vs: any) => ({ ...vs, longitude: target.lng, latitude: target.lat, zoom: 6.5, transitionDuration: 1200 }));
    }
  };

  const { linkifyText, linkifyChatText } = useLinkify(allPersons, allLocationNames, handlePersonClick, jumpToLocation);

  const handleFetchEvents = async () => {
    const params = new URLSearchParams({
      start: String(timeRange[0]), end: String(timeRange[1]),
      ...(filterPersonInclude && { person_include: filterPersonInclude }),
      ...(filterPersonOr && { person_or: filterPersonOr }),
      ...(filterEventType && { event_type: filterEventType }),
    });
    await replaceEvents(params);
  };

  const handleTimelineCommit = async (year: number) => {
    setTimelineYear(year);
    setTimeRange([year, year]);
    const params = new URLSearchParams({
      start: String(year), end: String(year),
      ...(filterPersonInclude && { person_include: filterPersonInclude }),
      ...(filterPersonOr && { person_or: filterPersonOr }),
      ...(filterEventType && { event_type: filterEventType }),
    });
    await replaceEvents(params);
  };

  const handleLoadMoreEvents = async () => {
    if (!eventsHasMore || eventsLoadingMore) return;
    setEventsLoadingMore(true);
    try {
      const { events, hasMore } = await fetchEventsPage(eventQueryParams, eventOffset, EVENT_PAGE_SIZE);
      setEventsList(current => {
        const existingIds = new Set(current.map((event: any) => event.id));
        const nextEvents = events.filter((event: any) => !existingIds.has(event.id));
        return [...current, ...nextEvents];
      });
      setEventOffset(current => current + events.length);
      setEventsHasMore(hasMore);
    } finally {
      setEventsLoadingMore(false);
    }
  };

  const handleMapEventHover = (info: any) => {
    if (hideTimer.current) clearTimeout(hideTimer.current);
    if (info.object && info.object.events && info.object.events.length > 0) {
      setHoveredEvent(info.object.events);
      setTooltipMode('modern');
      setHoverTooltipTop(info.y);
      setHoverTooltipLeft(info.x + 15);
    } else {
      hideTimer.current = setTimeout(() => setHoveredEvent(null), 100);
    }
  };

  const handleLocationClick = async (location: any) => {
    const { events, expandedLocations } = await fetchLocationEvents(location, 180, 280);
    setEventsList(events);
    setEventOffset(events.length);
    setEventsHasMore(false);
    setSelectedEventIds(new Set());
    setHighlightedLocNames(new Set(expandedLocations.length > 0 ? expandedLocations : [location.std_name]));
    setShowEventPanel(true);
    setViewState((vs: any) => ({ ...vs, longitude: location.lng, latitude: location.lat, zoom: Math.max(vs.zoom, 5.5), transitionDuration: 800 }));
  };

  const handleSendMessage = async (query: string) => {
    if (!query.trim() || isLoading) return;
    const newHistory = [...chatHistory, { role: 'user', content: query }];
    setChatHistory(newHistory);
    setChatInput('');
    setIsLoading(true);
    try {
      const answer = await sendMessage(query, newHistory);
      setChatHistory([...newHistory, { role: 'ai', content: answer }]);
    } catch {
      setChatHistory([...newHistory, { role: 'ai', content: '抱歉主公，臣未能联系上后台图谱引擎。请确认已运行 `python3 server.py`。' }]);
    } finally {
      setIsLoading(false);
    }
  };

  const focusEvent = (evt: any) => {
    setShowEventPanel(true);
    setRelationsModalOpen(false);
    setSelectedEventIds(new Set([evt.id]));

    const locs = new Set<string>();
    evt.locations?.forEach((l: string) => { if (l) locs.add(l); });
    setHighlightedLocNames(locs);

    const firstTarget = geoData.find(d => evt.locations?.some((l: string) => l && locationMatchesGeoName(l, d)));
    if (firstTarget) {
      setViewState((vs: any) => ({ ...vs, longitude: firstTarget.lng, latitude: firstTarget.lat, zoom: 6.0, transitionDuration: 1200 }));
    }
  };

  const handleRelationEventClick = async (eventId: string) => {
    const target = eventsList.find(evt => evt.id === eventId);
    if (target) {
      focusEvent(target);
      return;
    }

    const event = await fetchEventDetail(eventId);
    if (event) {
      setEventsList(current => current.some((evt: any) => evt.id === event.id) ? current : [event, ...current]);
      focusEvent(event);
    }
  };

  const clearAllEventSelections = () => {
    setSelectedEventIds(new Set());
    setHighlightedLocNames(new Set());
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
          firstTarget = geoData.find(d => e.locations.some((l: string) => l && locationMatchesGeoName(l, d)));
        }
      }
    });
    setHighlightedLocNames(allLocs);
    if (firstTarget && newSelected.size > 0) {
      setViewState((vs: any) => ({ ...vs, longitude: firstTarget.lng, latitude: firstTarget.lat, zoom: 6.0, transitionDuration: 1200 }));
    }
  };

  const handleSubmitEdit = async () => {
    try {
      const data = await submitFeedback({
        event_id: editTarget.id,
        event_title: editTarget.title,
        field_name: editField,
        proposed_value: editValue,
      });
      if (data.success) {
        alert('反馈提交成功，感谢您的修正！');
        setEditModalOpen(false);
      } else {
        alert('提交失败: ' + data.message);
      }
    } catch {
      alert('请求异常，请检查后端状态。');
    }
  };

  return (
    <div className="relative w-screen h-screen overflow-hidden bg-[#041527] font-sans p-6 flex items-center justify-center">
      <div className="relative w-full h-full border-2 border-[#5c6e83] rounded-lg overflow-hidden shadow-[0_0_30px_rgba(0,0,0,0.8)] bg-[#d2cdbe]">

        <MapView
          viewState={viewState}
          onViewStateChange={setViewState}
          geoData={geoData}
          highlightedLocNames={highlightedLocNames}
          onLocationClick={handleLocationClick}
          eventsList={showTimeline ? eventsList : []}
          allPersons={allPersons}
          onEventHover={handleMapEventHover}
        />


        <EventPanel
          show={showEventPanel}
          onToggle={setShowEventPanel}
          eventsList={eventsList}
          selectedEventIds={selectedEventIds}
          onToggleEvent={toggleEvent}
          onHoverEvent={(evt, top, panelWidth) => {
            if (hideTimer.current) clearTimeout(hideTimer.current);
            setHoverTooltipTop(top);
            setHoverTooltipLeft(panelWidth ? panelWidth + 20 : undefined);
            setHoveredEvent(evt);
          }}
          onLeaveEvent={() => { hideTimer.current = setTimeout(() => setHoveredEvent(null), 200); }}
          showFilter={showFilter}
          onToggleFilter={() => setShowFilter(v => !v)}
          timeRange={timeRange}
          setTimeRange={setTimeRange}
          filterPersonInclude={filterPersonInclude}
          setFilterPersonInclude={setFilterPersonInclude}
          filterPersonOr={filterPersonOr}
          setFilterPersonOr={setFilterPersonOr}
          filterEventType={filterEventType}
          setFilterEventType={setFilterEventType}
          filterMeta={filterMeta}
          onApplyFilter={() => { handleFetchEvents(); setShowFilter(false); }}
          onClearSelection={clearAllEventSelections}
          hasMore={eventsHasMore}
          isLoadingMore={eventsLoadingMore}
          onLoadMore={handleLoadMoreEvents}
        />

        <HoverTooltip
          event={hoveredEvent}
          top={hoverTooltipTop}
          left={hoverTooltipLeft}
          tooltipMode={tooltipMode}
          setTooltipMode={setTooltipMode}
          onMouseEnter={() => { if (hideTimer.current) clearTimeout(hideTimer.current); }}
          onMouseLeave={() => { hideTimer.current = setTimeout(() => setHoveredEvent(null), 100); }}
          onEdit={() => {
            setEditTarget(hoveredEvent);
            setEditField('locations');
            setEditValue(hoveredEvent.locations?.join(',') || '');
            setEditModalOpen(true);
            setHoveredEvent(null);
          }}
          renderDesc={(text) => linkifyText(text)}
        />

        <AgentPanel
          show={showAgentPanel}
          onToggle={setShowAgentPanel}
          chatHistory={chatHistory}
          isLoading={isLoading}
          chatInput={chatInput}
          setChatInput={setChatInput}
          onSend={handleSendMessage}
          renderMessage={(text) => linkifyChatText(text)}
        />

        <EditModal
          open={editModalOpen}
          target={editTarget}
          editField={editField}
          setEditField={setEditField}
          editValue={editValue}
          setEditValue={setEditValue}
          onClose={() => setEditModalOpen(false)}
          onSubmit={handleSubmitEdit}
        />

        <PersonRelationsModal
          open={relationsModalOpen}
          name={relationsPerson}
          relations={personRelations}
          loading={relationsLoading}
          onClose={() => setRelationsModalOpen(false)}
          onEventClick={handleRelationEventClick}
          onPersonClick={handlePersonClick}
        />

        {showTimeline ? (
          <TimelineSlider
            currentYear={timelineYear}
            onYearChange={setTimelineYear}
            onYearCommit={handleTimelineCommit}
            onClose={() => setShowTimeline(false)}
          />
        ) : (
          <button
            onClick={() => setShowTimeline(true)}
            className="absolute bottom-6 left-1/2 -translate-x-1/2 z-10 px-5 py-2.5 bg-gradient-to-r from-[#0a1628]/95 to-[#1a2f4c]/95 hover:from-[#1a2f4c] hover:to-[#0a1628] text-[#e2ddce] hover:text-[#f59e0b] border border-[#4a5f78]/70 rounded-full shadow-[0_4px_25px_rgba(0,0,0,0.7)] backdrop-blur-md flex items-center gap-2 text-xs font-serif font-bold tracking-wider transition-all duration-300 cursor-pointer hover:scale-105"
            title="点击展开时间轴"
          >
            <Calendar size={14} className="text-[#f59e0b]" />
            <span>{timelineYear} 年</span>
            <span className="text-[#8c9bab] font-sans font-normal border-l border-[#4a5f78]/60 pl-2 ml-1">展开时间轴</span>
          </button>
        )}

        {/* Mobile Orientation Guide Overlay */}
        {isPortraitMobile && (
          <div className="absolute inset-0 z-50 bg-[#041527] flex flex-col items-center justify-center p-8 text-center backdrop-blur-md">
            <style dangerouslySetInnerHTML={{
              __html: `
              @keyframes rotatePhone {
                0%, 100% { transform: rotate(0deg); }
                35%, 65% { transform: rotate(-90deg); }
              }
              .phone-rotate-anim {
                animation: rotatePhone 3s infinite ease-in-out;
              }
            `}} />

            <div className="relative w-16 h-28 border-4 border-[#f59e0b]/70 rounded-2xl flex items-center justify-center phone-rotate-anim shadow-[0_0_15px_rgba(245,158,11,0.2)] mb-8">
              <div className="absolute top-2 left-1/2 -translate-x-1/2 w-8 h-1 bg-[#f59e0b]/50 rounded-full" />
              <div className="absolute bottom-2 left-1/2 -translate-x-1/2 w-3 h-3 border border-[#f59e0b]/50 rounded-full" />
              <div className="text-[#f59e0b] font-serif text-[10px] font-bold tracking-widest uppercase rotate-90 select-none">Han Map</div>
            </div>

            <h2 className="text-xl font-bold text-[#e2ddce] tracking-[0.2em] font-serif mb-3 select-none">
              「主公，请横屏观天下」
            </h2>
            <p className="text-slate-400 text-sm leading-relaxed max-w-sm font-serif select-none mb-6">
              三国疆域辽阔，军势非广阔视野不能容载。<br />
              请转动您的手机为<strong>横屏</strong>，以开启宏大的数字沙盘。
            </p>

            <button
              onClick={async () => {
                try {
                  const docEl = document.documentElement as any;
                  // Android / Chrome / WebView / Safari vendor-prefixed fullscreen logic
                  const reqFs = docEl.requestFullscreen || 
                                docEl.webkitRequestFullscreen || 
                                docEl.webkitRequestFullScreen || 
                                docEl.mozRequestFullScreen || 
                                docEl.msRequestFullscreen;
                  if (reqFs) {
                    await reqFs.call(docEl);
                  }
                  
                  // Vendor-prefixed orientation locking logic
                  const anyScreen = screen as any;
                  const orientation = anyScreen.orientation || anyScreen.mozOrientation || anyScreen.msOrientation;
                  if (orientation && orientation.lock) {
                    await orientation.lock('landscape');
                  } else if (anyScreen.lockOrientation) {
                    anyScreen.lockOrientation('landscape');
                  }
                } catch (err) {
                  // Fallback
                }
              }}
              className="px-6 py-2.5 bg-gradient-to-r from-[#1a2f4c] to-[#0a1628] hover:from-[#1a2f4c] hover:to-[#1a2f4c] text-[#f59e0b] border border-[#f59e0b]/40 hover:border-[#f59e0b] rounded-md shadow-lg text-xs font-serif tracking-wider transition-all duration-200 cursor-pointer"
            >
              一键尝试全屏旋转
            </button>

            <span className="text-[10px] text-slate-500 font-sans mt-3 select-none">
              （若已横置，请确认手机系统的“自动旋转”或“方向锁定”已开启）
            </span>
          </div>
        )}

      </div>
    </div>
  );
}
