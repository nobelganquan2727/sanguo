'use client';

import { useState, useRef } from 'react';
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

const INITIAL_VIEW_STATE = { longitude: 108.5, latitude: 34.0, zoom: 4.2, pitch: 0, bearing: 0 };
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://124.222.133.106:8000';
const EVENT_PAGE_SIZE = 100;
console.log('API_BASE:', API_BASE, process.env.NEXT_PUBLIC_API_BASE);

export default function Home() {
  const [viewState, setViewState] = useState(INITIAL_VIEW_STATE);
  const [timeRange, setTimeRange] = useState([190, 195]);
  const [timelineYear, setTimelineYear] = useState(190);

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
  const [personRelations, setPersonRelations] = useState<any[]>([]);
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
    setPersonRelations([]);
    await loadPersonEvents(name);
    const relations = await fetchPersonRelations(name);
    setPersonRelations(relations);
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
          eventsList={eventsList}
          allPersons={allPersons}
          onEventHover={handleMapEventHover}
        />

        {/* Title */}
        <div className="absolute top-4 left-1/2 -translate-x-1/2 z-10 pointer-events-none">
          <div className="px-16 py-3 bg-gradient-to-b from-[#1a2f4c] to-[#0a1628] border border-[#4a5f78] rounded-md shadow-lg flex items-center gap-6">
            <div className="h-px w-12 bg-gradient-to-r from-transparent to-[#4a5f78]" />
            <h1 className="text-2xl font-bold text-white tracking-[0.2em] font-serif" style={{ textShadow: '0 2px 4px rgba(0,0,0,0.8)' }}>三国志</h1>
            <div className="h-px w-12 bg-gradient-to-l from-transparent to-[#4a5f78]" />
          </div>
        </div>

        <EventPanel
          show={showEventPanel}
          onToggle={setShowEventPanel}
          eventsList={eventsList}
          selectedEventIds={selectedEventIds}
          onToggleEvent={toggleEvent}
          onHoverEvent={(evt, top) => {
            if (hideTimer.current) clearTimeout(hideTimer.current);
            setHoverTooltipTop(top);
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
        />

        <TimelineSlider
          currentYear={timelineYear}
          onYearChange={setTimelineYear}
          onYearCommit={handleTimelineCommit}
        />

      </div>
    </div>
  );
}
