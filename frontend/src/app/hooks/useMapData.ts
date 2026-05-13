'use client';

import { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://124.222.133.106:8000';

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

  const addPoint = (point: AdminPoint, province?: string, commandery?: string) => {
    const lat = point.lat ?? point.center?.lat;
    const lng = point.lng ?? point.center?.lng;
    if (typeof lat !== 'number' || typeof lng !== 'number') return;

    const key = `${point.level}:${province ?? ''}:${commandery ?? ''}:${point.name}`;
    uniqueLocs.set(key, {
      std_name: point.name,
      lat,
      lng,
      level: point.level,
      province,
      commandery,
      aliases: point.aliases ?? [],
      region: point.region ?? [province, commandery].filter(Boolean).join('-'),
    });
  };

  data.provinces?.forEach(province => {
    addPoint(province, province.name);

    province.commanderies?.forEach(commandery => {
      addPoint(commandery, province.name, commandery.name);

      commandery.counties?.forEach(county => {
        addPoint(county, province.name, commandery.name);
      });
    });
  });

  return Array.from(uniqueLocs.values());
}

export function useMapData() {
  const [geoData, setGeoData] = useState<any[]>([]);
  const [eventsList, setEventsList] = useState<any[]>([]);
  const [filterMeta, setFilterMeta] = useState<{ locations: string[]; event_types: string[] }>({ locations: [], event_types: [] });
  const [allPersons, setAllPersons] = useState<string[]>([]);

  useEffect(() => {
    fetch('/eastern_han_admin.json').then(r => r.json()).then(data => {
      setGeoData(flattenAdminGeo(data));
    });

    fetch(`${API_BASE}/api/filter-meta`).then(r => r.json()).then(setFilterMeta).catch(() => {});

    fetch(`${API_BASE}/api/persons`).then(r => r.json()).then((d: any) => {
      const sorted = [...(d.persons || [])].sort((a: string, b: string) => b.length - a.length);
      setAllPersons(sorted);
    }).catch(() => {});

    fetch(`${API_BASE}/api/events?start=190&end=195`).then(r => r.json()).then((d: any) => {
      setEventsList(d.events || []);
    }).catch(() => {});
  }, []);

  const fetchEvents = async (params: URLSearchParams) => {
    try {
      const res = await fetch(`${API_BASE}/api/events?${params}`);
      const data = await res.json();
      return data.events || [];
    } catch (err) {
      console.error(err);
      return [];
    }
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
      return data.relations || [];
    } catch (err) {
      console.error(err);
      return [];
    }
  };

  const sendMessage = async (query: string, chatHistory: { role: string; content: string }[]) => {
    const res = await fetch(`${API_BASE}/api/ask`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ question: query }),
    });
    const data = await res.json();
    return data.answer as string;
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
    fetchLocationEvents,
    fetchPersonRelations,
    sendMessage,
    submitFeedback,
  };
}
