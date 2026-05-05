'use client';

import { useState, useEffect } from 'react';

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? 'http://124.222.133.106:8000';

export function useMapData() {
  const [geoData, setGeoData] = useState<any[]>([]);
  const [eventsList, setEventsList] = useState<any[]>([]);
  const [filterMeta, setFilterMeta] = useState<{ locations: string[]; event_types: string[] }>({ locations: [], event_types: [] });
  const [allPersons, setAllPersons] = useState<string[]>([]);

  useEffect(() => {
    fetch('/geo.json').then(r => r.json()).then(data => {
      const uniqueLocs = new Map();
      Object.values(data).flat().forEach((loc: any) => {
        if (loc.lat && loc.lng) uniqueLocs.set(loc.std_name, loc);
      });
      setGeoData(Array.from(uniqueLocs.values()));
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

  return { geoData, eventsList, setEventsList, filterMeta, allPersons, fetchEvents, sendMessage, submitFeedback };
}
