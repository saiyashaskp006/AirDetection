const API_URL = import.meta.env.VITE_API_URL || "http://localhost:8000";

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
  return `${API_URL.replace(/^http/, "ws")}/ws/readings`;
}
