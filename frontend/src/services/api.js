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
  const finalHeaders = { ...headers };
  // Only send a JSON content type when there is a body. A content type on a
  // GET turns a simple request into a CORS preflight, which doubles the number
  // of requests once the dashboard is polling over the internet.
  if (rest.body != null) finalHeaders["Content-Type"] = "application/json";
  let response;
  try {
    response = await fetch(`${API_URL}${path}`, {
      ...rest,
      headers: finalHeaders,
    });
  } catch (reason) {
    // Browsers deliberately hide CORS details and report only "Failed to
    // fetch". Include the URL and origin so the deployment mistake is obvious.
    if (reason instanceof TypeError) {
      const origin = typeof window !== "undefined" ? window.location.origin : "this site";
      throw new Error(
        `Could not reach the API at ${API_URL}. Check that the Pi backend is running, `
        + `that VITE_API_URL is HTTPS, and that FRONTEND_ORIGINS contains ${origin}.`,
      );
    }
    throw reason;
  }
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
