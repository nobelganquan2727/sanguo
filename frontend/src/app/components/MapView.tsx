'use client';

import DeckGL from '@deck.gl/react';
import MapGL from 'react-map-gl/maplibre';
import { ScatterplotLayer, TextLayer } from '@deck.gl/layers';
import 'maplibre-gl/dist/maplibre-gl.css';
import { useCallback } from 'react';

const MAP_STYLE = 'https://basemaps.cartocdn.com/gl/voyager-nolabels-gl-style/style.json';

interface MapViewProps {
  viewState: any;
  onViewStateChange: (vs: any) => void;
  geoData: any[];
  highlightedLocNames: Set<string>;
}

export default function MapView({ viewState, onViewStateChange, geoData, highlightedLocNames }: MapViewProps) {
  const isHL = useCallback(
    (name: string) => [...highlightedLocNames].some(l => l && (l.includes(name) || name.includes(l))),
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
    let shouldShow = false;

    if (hasSelection) {
      shouldShow = highlighted || name.endsWith('州') || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
    } else {
      if (viewState.zoom >= 5.0) {
        shouldShow = name.endsWith('州') || name.endsWith('郡') || name.endsWith('国') ||
          ['洛阳', '长安', '邺城', '建业', '许昌', '成都', '襄阳', '江陵', '汉中', '宛城'].includes(name);
      } else {
        shouldShow = name.endsWith('州') || ['洛阳', '长安', '建业', '成都', '邺城', '许昌'].includes(name);
      }
    }

    if (!shouldShow) continue;
    const overlap = visibleData.some(
      v => Math.abs(v.lng - d.lng) < overlapThreshold && Math.abs(v.lat - d.lat) < overlapThreshold,
    );
    if (!overlap) visibleData.push(d);
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
      onClick: () => {},
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
      updateTriggers: { getSize: [highlightedLocNames], getColor: [highlightedLocNames] },
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
