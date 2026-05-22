'use client';

import DeckGL from '@deck.gl/react';
import MapGL from 'react-map-gl/maplibre';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useCallback } from 'react';
import { locationNameMatches, locationMatchesGeoName } from '../utils/locationMatch';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-nolabels-gl-style/style.json';

interface MapViewProps {
  viewState: any;
  onViewStateChange: (vs: any) => void;
  geoData: any[];
  highlightedLocNames: Set<string>;
  onLocationClick?: (location: any) => void;
  eventsList?: any[];
  allPersons?: string[];
  onEventHover?: (info: any) => void;
}

export default function MapView({ viewState, onViewStateChange, geoData, highlightedLocNames, onLocationClick, eventsList, allPersons, onEventHover }: MapViewProps) {
  const isHL = useCallback(
    (name: string) => [...highlightedLocNames].some(l => l && locationNameMatches(l, name)),
    [highlightedLocNames],
  );

  const hasSelection = highlightedLocNames.size > 0;
  const visibleData: any[] = [];
  const overlapThreshold = 1.5 / viewState.zoom;

  const sortedGeo = [...geoData].sort((a, b) => {
    const aHL = isHL(a.std_name || '');
    const bHL = isHL(b.std_name || '');
    return (bHL ? 1 : 0) - (aHL ? 1 : 0);
  });

  for (const d of sortedGeo) {
    const name = d.std_name || '';
    const highlighted = isHL(name);
    const level = d.level || 'county';
    let shouldShow = false;

    if (hasSelection) {
      shouldShow = highlighted || level === 'province' || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
    } else {
      if (viewState.zoom >= 5.0) {
        shouldShow = level === 'province' || level === 'commandery' ||
          ['洛阳', '长安', '邺城', '建业', '许昌', '成都', '襄阳', '江陵', '汉中', '宛城'].includes(name);
      } else {
        shouldShow = level === 'province' || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
      }
    }

    if (!shouldShow) continue;
    const overlap = visibleData.some(
      v => Math.abs(v.lng - d.lng) < overlapThreshold && Math.abs(v.lat - d.lat) < overlapThreshold,
    );
    if (!overlap) visibleData.push(d);
  }

  const eventPoints: any[] = [];
  if (eventsList && eventsList.length > 0) {
    const TYPE_PRIORITY: Record<string, number> = {
      '军事征伐': 3,
      '政治谋虑': 2,
      '政治谋略': 2,
      '内政治理': 1,
    };
    const getPriority = (type?: string) => (type && TYPE_PRIORITY[type]) || 0;

    const seenTitles = new Set<string>();
    const validEvents: any[] = [];

    for (const evt of eventsList) {
      if (!evt.locations || evt.locations.length === 0) continue;
      
      if (seenTitles.has(evt.title)) continue;
      seenTitles.add(evt.title);

      if (evt.year == null) continue;

      const prio = getPriority(evt.type);
      if (prio === 0) continue;

      const firstLoc = evt.locations.find((l: string) => l);
      if (!firstLoc) continue;
      
      const geo = geoData.find(d => locationMatchesGeoName(firstLoc, d));
      if (geo) {
        validEvents.push({ ...evt, lng: geo.lng, lat: geo.lat, priority: prio });
      }
    }
    
    // 展示所有匹配类型的事件
    validEvents.sort((a, b) => b.priority - a.priority);

    // 计算重叠，将重叠的事件聚合
    const lngThreshold = 6.0 / viewState.zoom;
    const latThreshold = 2.0 / viewState.zoom;
    const groupedEvents: any[][] = [];

    for (const evt of validEvents) {
      let placed = false;
      for (const group of groupedEvents) {
        const center = group[0];
        if (Math.abs(center.lng - evt.lng) < lngThreshold && Math.abs(center.lat - evt.lat) < latThreshold) {
          group.push(evt);
          placed = true;
          break;
        }
      }
      if (!placed) {
        groupedEvents.push([evt]);
      }
    }

    const getShortLabel = (title: string) => {
      if (allPersons && allPersons.length > 0) {
        for (const p of allPersons) {
          if (title.startsWith(p)) {
            return p;
          }
        }
      }
      return title.length > 4 ? title.substring(0, 4) : title;
    };

    for (const group of groupedEvents) {
      const topEvent = group[0];
      const shortTitle = getShortLabel(topEvent.title);
      
      const type = topEvent.type || '';
      const isRed = type === '军事征伐' || type === '政治谋略' || type === '政治谋虑';
      const bgColor = isRed ? [185, 28, 28, 220] : [20, 83, 45, 220];
      const borderColor = isRed ? [239, 68, 68, 255] : [34, 197, 94, 255];

      eventPoints.push({
        lng: topEvent.lng,
        lat: topEvent.lat,
        label: group.length > 1 ? `${shortTitle} 等${group.length}件` : shortTitle,
        events: group,
        bgColor,
        borderColor,
      });
    }
  }

  const layers = [
    new ScatterplotLayer({
      id: 'cities-layer',
      data: visibleData,
      getPosition: (d: any) => [d.lng, d.lat],
      getFillColor: (d: any) => isHL(d.std_name) ? [252, 211, 77, 255] : [185, 28, 28, 200],
      getRadius: (d: any) => isHL(d.std_name) ? 18000 : 8000,
      radiusMinPixels: 3,
      radiusMaxPixels: 10,
      pickable: true,
      updateTriggers: { getFillColor: [highlightedLocNames], getRadius: [highlightedLocNames] },
      onClick: (info: any) => {
        if (info.object) onLocationClick?.(info.object);
      },
    }),
    new TextLayer({
      id: 'cities-text-layer',
      data: visibleData,
      getPosition: (d: any) => [d.lng, d.lat],
      getText: (d: any) => d.std_name,
      getSize: (d: any) => isHL(d.std_name) ? 16 : 12,
      getColor: (d: any) => isHL(d.std_name) ? [245, 158, 11, 255] : [41, 37, 36, 255],
      getAlignmentBaseline: 'bottom',
      getPixelOffset: [0, -10],
      fontFamily: 'Noto Serif SC, serif',
      fontWeight: 'bold',
      characterSet: 'auto',
      pickable: true,
      onClick: (info: any) => {
        if (info.object) onLocationClick?.(info.object);
      },
      updateTriggers: { getSize: [highlightedLocNames], getColor: [highlightedLocNames] },
    }),
    new TextLayer({
      id: 'events-text-layer',
      data: eventPoints,
      getPosition: (d: any) => [d.lng, d.lat],
      getText: (d: any) => d.label,
      getSize: 13,
      getColor: [255, 255, 255, 255],
      getBackgroundColor: (d: any) => d.bgColor || [26, 47, 76, 230],
      getBorderColor: (d: any) => d.borderColor || [245, 158, 11, 255],
      getBorderWidth: 1,
      background: true,
      backgroundPadding: [6, 4, 6, 4],
      getAlignmentBaseline: 'top',
      getPixelOffset: [0, 15],
      fontFamily: 'Noto Serif SC, serif',
      fontWeight: 'bold',
      characterSet: 'auto',
      pickable: true,
      onHover: (info: any) => {
        if (onEventHover) onEventHover(info);
      },
      updateTriggers: {
        getText: [eventsList],
        getBackgroundColor: [eventsList],
        getBorderColor: [eventsList],
      }
    }),
  ];

  return (
    <div className="absolute inset-0 z-0 opacity-90 mix-blend-multiply">
      <DeckGL
        viewState={viewState}
        onViewStateChange={({ viewState: vs }) => {
          if ('longitude' in vs && 'latitude' in vs && 'zoom' in vs) {
            onViewStateChange({
              longitude: vs.longitude,
              latitude: vs.latitude,
              zoom: vs.zoom,
              pitch: vs.pitch ?? 0,
              bearing: vs.bearing ?? 0,
            });
          }
        }}
        controller={true}
        layers={layers}
      >
        <MapGL mapStyle={MAP_STYLE} />
      </DeckGL>
    </div>
  );
}
