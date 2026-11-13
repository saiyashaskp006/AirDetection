import { useEffect } from "react";
import { CircleMarker, MapContainer, TileLayer, useMap, useMapEvents } from "react-leaflet";

const position = (latitude, longitude) => [latitude, longitude];

function MapClick({ onSelect }) {
  useMapEvents({
    click(event) {
      onSelect(event.latlng.lat, event.latlng.lng, "Map selection");
    },
  });
  return null;
}

function MapCamera({ locations }) {
  const map = useMap();
  const cameraKey = locations
    .map((site) => `${site.latitude},${site.longitude}`)
    .join("|");
  useEffect(() => {
    if (locations.length === 1) {
      map.flyTo(position(locations[0].latitude, locations[0].longitude), 12, { duration: 0.6 });
    } else if (locations.length > 1) {
      const bounds = locations.map((site) => position(site.latitude, site.longitude));
      map.fitBounds(bounds, { padding: [30, 30], maxZoom: 12 });
    }
    // Refit only when the coordinates change, not on every 1 Hz reading.
  }, [cameraKey]); // eslint-disable-line react-hooks/exhaustive-deps
  return null;
}

export function LocationMap({ locations, onSelect, selectedCenter }) {
  return (
    <div className="location-map">
      <MapContainer center={[20, 0]} zoom={2} scrollWheelZoom className="leaflet-map">
        <TileLayer
          attribution='&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
          url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png"
        />
        <MapClick onSelect={onSelect} />
        <MapCamera locations={locations} />
        {locations.map((site) => (
          <CircleMarker
            key={`${site.location_name}:${site.latitude}:${site.longitude}`}
            center={position(site.latitude, site.longitude)}
            radius={selectedCenter && selectedCenter.latitude === site.latitude && selectedCenter.longitude === site.longitude ? 10 : 7}
            pathOptions={{
              color: "#081720",
              weight: 2,
              fillColor: site.latest?.source === "simulation" ? "#f6bd60" : "#59d9ae",
              fillOpacity: 0.95,
            }}
            eventHandlers={{
              click: () => onSelect(site.latitude, site.longitude, site.location_name),
            }}
          />
        ))}
        {selectedCenter && (
          <CircleMarker
            center={position(selectedCenter.latitude, selectedCenter.longitude)}
            radius={13}
            pathOptions={{ color: "#58b8ff", weight: 2, fillColor: "#58b8ff", fillOpacity: 0.18 }}
            interactive={false}
          />
        )}
      </MapContainer>
      <div className="map-attribution-note">Map tiles © OpenStreetMap contributors</div>
    </div>
  );
}
