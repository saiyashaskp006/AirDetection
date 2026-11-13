const pageHost = typeof window !== "undefined" ? window.location.hostname : "localhost";
const isLoopback = (host) => host === "localhost" || host === "127.0.0.1" || host === "::1";

/**
 * Vite's dev server is often opened from another device on the LAN, for
 * example http://192.168.1.50:5173. In that case "localhost" would point at
 * the phone/laptop running the browser, not at the API. Keep an explicit
 * VITE_API_URL, but rewrite a loopback host to the page host so LAN access
 * works without editing the environment.
 */
function resolveUrl(configured, fallback) {
  if (!configured) return fallback;
  try {
    const url = new URL(configured);
    if (!isLoopback(pageHost) && isLoopback(url.hostname)) {
      url.hostname = pageHost;
      return url.toString().replace(/\/$/, "");
    }
  } catch {
    return configured;
  }
  return configured.replace(/\/$/, "");
}

const API_URL = resolveUrl(
  import.meta.env.VITE_API_URL,
  `http://${isLoopback(pageHost) ? "localhost" : pageHost}:8000`,
);

const DEFAULT_WS_URL = `${API_URL.replace(/^http/, "ws")}/ws/readings`;
const WS_URL = resolveUrl(import.meta.env.VITE_WS_URL, DEFAULT_WS_URL);

// "cloud" = API + MongoDB, "direct" = API running on the Raspberry Pi.
export const dataMode = import.meta.env.VITE_DATA_MODE || "cloud";

export { API_URL };

export async function api(path, options = {}) {
  const { headers, ...rest } = options;
  const response = await fetch(`${API_URL}${path}`, {
    ...rest,
    headers: { "Content-Type": "application/json", ...headers },
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
