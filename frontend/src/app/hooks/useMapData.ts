'use client';

import { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://127.0.0.1:8000';
const DEFAULT_EVENT_PAGE_SIZE = 100;

type AdminPoint = {
  name: string;
  level: 'province' | 'commandery' | 'county';
  center?: { lat?: number; lng?: number } | null;
  lat?: number | null;
  lng?: number | null;
  aliases?: string[];
  region?: string;
};

type AdminCommandery = AdminPoint & {
  type?: string;
  counties?: AdminPoint[];
};

type AdminProvince = AdminPoint & {
  commanderies?: AdminCommandery[];
};

type AdminGeo = {
  provinces?: AdminProvince[];
};

function flattenAdminGeo(data: AdminGeo) {
  const uniqueLocs = new Map<string, any>();

  const levelRank = { province: 3, commandery: 2, county: 1 };

  const shouldReplacePoint = (current: any | undefined, next: any) => {
    if (!current) return true;
    if (levelRank[next.level as keyof typeof levelRank] !== levelRank[current.level as keyof typeof levelRank]) {
      return levelRank[next.level as keyof typeof levelRank] > levelRank[current.level as keyof typeof levelRank];
    }
    if ((next.childCount ?? 0) !== (current.childCount ?? 0)) {
      return (next.childCount ?? 0) > (current.childCount ?? 0);
    }
    if ((next.aliasCount ?? 0) !== (current.aliasCount ?? 0)) {
      return (next.aliasCount ?? 0) > (current.aliasCount ?? 0);
    }
    return false;
  };

  const addPoint = (point: AdminPoint, province?: string, commandery?: string, childCount = 0) => {
    const lat = point.lat ?? point.center?.lat;
    const lng = point.lng ?? point.center?.lng;
    if (typeof lat !== 'number' || typeof lng !== 'number') return;

    const key = point.name;
    const nextPoint = {
      std_name: point.name,
      lat,
      lng,
      level: point.level,
      province,
      commandery,
      aliases: point.aliases ?? [],
      aliasCount: point.aliases?.length ?? 0,
      childCount,
      region: point.region ?? [province, commandery].filter(Boolean).join('-'),
    };

    if (shouldReplacePoint(uniqueLocs.get(key), nextPoint)) {
      uniqueLocs.set(key, nextPoint);
    }
  };

  data.provinces?.forEach(province => {
    const provinceChildCount = province.commanderies?.reduce(
      (count, commandery) => count + (commandery.counties?.length ?? 0),
      0,
    ) ?? 0;
    addPoint(province, province.name, undefined, provinceChildCount);

    province.commanderies?.forEach(commandery => {
      addPoint(commandery, province.name, commandery.name, commandery.counties?.length ?? 0);

      commandery.counties?.forEach(county => {
        addPoint(county, province.name, commandery.name);
      });
    });
  });

  return Array.from(uniqueLocs.values());
}

const getOrCreateUserId = (): string => {
  if (typeof window === 'undefined') return '';
  let stored = localStorage.getItem('sanguo_user_id');
  if (!stored) {
    try {
      stored = `usr_${crypto.randomUUID()}`;
    } catch (e) {
      stored = `usr_${Math.random().toString(36).substring(2, 15)}_${Date.now().toString(36)}`;
    }
    localStorage.setItem('sanguo_user_id', stored);
  }
  return stored;
};

export function useMapData() {
  const [geoData, setGeoData] = useState<any[]>([]);
  const [eventsList, setEventsList] = useState<any[]>([]);
  const [filterMeta, setFilterMeta] = useState<{ locations: string[]; event_types: string[] }>({ locations: [], event_types: [] });
  const [allPersons, setAllPersons] = useState<string[]>([]);
  const [mapLoading, setMapLoading] = useState(true);
  const [sessionId, setSessionId] = useState<string>('');

  useEffect(() => {
    // Generate a unique session ID for the current browser session
    setSessionId(`sess_${Math.random().toString(36).substring(2, 15)}_${Date.now().toString(36)}`);

    setMapLoading(true);
    const p1 = fetch(`${API_BASE}/api/eastern-han-admin`).then(r => r.json()).then(data => {
      setGeoData(flattenAdminGeo(data));
    }).catch(() => {});

    const p2 = fetch(`${API_BASE}/api/filter-meta`).then(r => r.json()).then(setFilterMeta).catch(() => { });

    const p3 = fetch(`${API_BASE}/api/persons`).then(r => r.json()).then((d: any) => {
      const sorted = [...(d.persons || [])].sort((a: string, b: string) => b.length - a.length);
      setAllPersons(sorted);
    }).catch(() => { });

    const p4 = fetch(`${API_BASE}/api/events?start=190&end=195&limit=${DEFAULT_EVENT_PAGE_SIZE}&offset=0`).then(r => r.json()).then((d: any) => {
      setEventsList(d.events || []);
    }).catch(() => { });

    Promise.all([p1, p2, p3, p4]).finally(() => {
      setMapLoading(false);
    });
  }, []);

  const fetchEventsPage = async (params: URLSearchParams, offset = 0, limit = DEFAULT_EVENT_PAGE_SIZE) => {
    try {
      const pageParams = new URLSearchParams(params);
      pageParams.set('limit', String(limit));
      pageParams.set('offset', String(offset));
      const res = await fetch(`${API_BASE}/api/events?${pageParams}`);
      const data = await res.json();
      return { events: data.events || [], hasMore: Boolean(data.has_more) };
    } catch (err) {
      console.error(err);
      return { events: [], hasMore: false };
    }
  };

  const fetchEvents = async (params: URLSearchParams) => {
    const { events } = await fetchEventsPage(params, 0, DEFAULT_EVENT_PAGE_SIZE);
    return events;
  };

  const fetchLocationEvents = async (location: any, start = 180, end = 280) => {
    try {
      const params = new URLSearchParams({
        name: location.std_name,
        level: location.level ?? 'county',
        start: String(start),
        end: String(end),
        ...(location.province && { province: location.province }),
        ...(location.commandery && { commandery: location.commandery }),
      });
      const res = await fetch(`${API_BASE}/api/location-events?${params}`);
      const data = await res.json();
      return { events: data.events || [], expandedLocations: data.expanded_locations || [] };
    } catch (err) {
      console.error(err);
      return { events: [], expandedLocations: [] };
    }
  };

  const fetchPersonRelations = async (name: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/person-relations/${encodeURIComponent(name)}`);
      const data = await res.json();
      return data;
    } catch (err) {
      console.error(err);
      return {
        name,
        hometown: null,
        clan: null,
        nodes: [{ id: name, label: name, type: 'center' }],
        links: [],
        relations: []
      };
    }
  };

  const fetchEventDetail = async (eventId: string) => {
    try {
      const res = await fetch(`${API_BASE}/api/events/${encodeURIComponent(eventId)}`);
      const data = await res.json();
      return data.event || null;
    } catch (err) {
      console.error(err);
      return null;
    }
  };

  const sendMessage = async (
    query: string,
    chatHistory: { role: string; content: string }[],
    onChunk: (chunk: { type: 'status' | 'text' | 'done' | 'events' | 'clarify'; content: string }) => void,
    signal?: AbortSignal
  ) => {
    const currentUserId = getOrCreateUserId();
    const res = await fetch(`${API_BASE}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ 
        question: query, 
        history: chatHistory,
        session_id: sessionId,
        user_id: currentUserId
      }),
      signal
    });

    if (!res.body) return;
    const reader = res.body.getReader();
    const decoder = new TextDecoder('utf-8');
    let buffer = '';

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n');
      buffer = lines.pop() ?? '';

      for (const line of lines) {
        if (!line.trim()) continue;
        try {
          const parsed = JSON.parse(line);
          onChunk(parsed);
        } catch (e) {
          console.error("Failed to parse SSE JSON chunk", line, e);
        }
      }
    }

    // flush remaining buffer
    if (buffer.trim()) {
      try {
        onChunk(JSON.parse(buffer));
      } catch (e) { /* ignore */ }
    }
  };

  const submitFeedback = async (payload: {
    event_id: string;
    event_title: string;
    field_name: string;
    proposed_value: string;
  }) => {
    const res = await fetch(`${API_BASE}/api/feedback`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    });
    return res.json();
  };

  return {
    geoData,
    eventsList,
    setEventsList,
    filterMeta,
    allPersons,
    fetchEvents,
    fetchEventsPage,
    fetchLocationEvents,
    fetchPersonRelations,
    fetchEventDetail,
    sendMessage,
    submitFeedback,
    mapLoading,
    setMapLoading,
  };
}
