const API_URL = (import.meta.env.VITE_API_URL || "http://localhost:8000").replace(/\/$/, "");

const DEFAULT_WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/readings`;
const WS_URL = import.meta.env.VITE_WS_URL || DEFAULT_WS_URL;

// "cloud" = API + MongoDB, "direct" = API running on the Raspberry Pi.
export const dataMode = import.meta.env.VITE_DATA_MODE || "cloud";

export { API_URL };

export async function api(path, options = {}) {
  const response = await fetch(`${API_URL}${path}`, {
    headers: { "Content-Type": "application/json", ...options.headers },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || `Request failed (${response.status})`);
  }
  if (response.status === 204) return null;
  return response.json();
}

export function websocketUrl() {
  return WS_URL;
}
