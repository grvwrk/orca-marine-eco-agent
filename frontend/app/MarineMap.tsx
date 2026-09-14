'use client';

import { useEffect } from 'react';
import type { ComponentType, ReactNode } from 'react';
import { CircleMarker, MapContainer, Popup, TileLayer, useMap } from 'react-leaflet';

type MapContainerProps = {
  center: [number, number];
  zoom: number;
  scrollWheelZoom?: boolean;
  className?: string;
  children?: ReactNode;
};

const TypedMapContainer = MapContainer as unknown as ComponentType<MapContainerProps>;

type MapPoint = {
  lat: number;
  lon: number;
  label: string;
  index: number;
};

type MarineMapProps = {
  center: { lat: number; lon: number };
  points: MapPoint[];
  onEvidenceSelect: (index: number) => void;
};

function MapController({ target }: { target: { lat: number; lon: number } }) {
  const map = useMap();

  useEffect(() => {
    if (Number.isFinite(target.lat) && Number.isFinite(target.lon)) {
      map.flyTo([target.lat, target.lon], 7, { duration: 1 });
    }
  }, [map, target]);

  return null;
}

export default function MarineMap({ center, points, onEvidenceSelect }: MarineMapProps) {
  return (
    <TypedMapContainer center={[center.lat, center.lon]} zoom={7} scrollWheelZoom className="leaflet-map">
      <TileLayer url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <MapController target={center} />
      {points.map((point) => (
        <CircleMarker
          key={`${point.label}-${point.lat}-${point.lon}`}
          center={[point.lat, point.lon]}
          pathOptions={{ color: point.index === -1 ? '#ff6247' : '#075b6f', fillColor: point.index === -1 ? '#ff6247' : '#94e2ed', fillOpacity: 0.8 }}
          eventHandlers={{ click: () => { if (point.index >= 0) onEvidenceSelect(point.index); } }}
        >
          <Popup>{point.label}</Popup>
        </CircleMarker>
      ))}
    </TypedMapContainer>
  );
}