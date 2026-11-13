import { useCallback, useEffect, useRef, useState } from "react";
import { api, websocketUrl } from "../services/api";

const HISTORY_LIMIT = 120;
const AUX_REFRESH_MS = 8000;
const POLL_MS = 2000;
const LIVE_WINDOW_MS = 5000;

const rowKey = (row) => row?.id ?? row?.timestamp;

function mergeHistory(previous, incoming) {
  const merged = new Map();
  for (const row of previous) {
    if (row) merged.set(rowKey(row), row);
  }
  for (const row of incoming) {
    if (row) merged.set(rowKey(row), row);
  }
  return [...merged.values()]
    .filter((row) => row?.timestamp)
    .sort((a, b) => new Date(a.timestamp) - new Date(b.timestamp))
    .slice(-HISTORY_LIMIT);
}

function safeWebSocketUrl() {
  const configured = websocketUrl();
  if (!/^wss?:\/\//i.test(configured)) {
    return configured.replace(/^http/i, "ws");
  }
  return configured;
}

export function useLiveData() {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [sensors, setSensors] = useState([]);
  const [socketStatus, setSocketStatus] = useState("connecting");
  const [error, setError] = useState("");
  const [lastUpdate, setLastUpdate] = useState(0);

  const lastAuxRefresh = useRef(0);
  const lastMessageAt = useRef(0);
  const latestKey = useRef(null);
  const latestTime = useRef(0);

  const applyReading = useCallback((reading) => {
    if (!reading) return;
    const key = rowKey(reading);
    // Polling and the WebSocket can see the same reading; update once.
    if (key != null && key === latestKey.current) return;
    const incomingTime = reading.timestamp ? new Date(reading.timestamp).getTime() : 0;
    // Ignore a late/out-of-order reading that is older than the current one.
    if (incomingTime && latestTime.current && incomingTime < latestTime.current) return;
    latestKey.current = key;
    if (incomingTime) latestTime.current = incomingTime;
    setLatest(reading);
    setHistory((previous) => mergeHistory(previous, [reading]));
    setLastUpdate(Date.now());
  }, []);

  const refreshAux = useCallback(async (force = false) => {
    const now = Date.now();
    if (!force && now - lastAuxRefresh.current < AUX_REFRESH_MS) return;
    lastAuxRefresh.current = now;
    const [alertResult, sensorResult] = await Promise.allSettled([
      api("/api/alerts?limit=1000"),
      api("/api/sensors/status"),
    ]);
    if (alertResult.status === "fulfilled") setAlerts(alertResult.value);
    if (sensorResult.status === "fulfilled") setSensors(sensorResult.value);
  }, []);

  const refresh = useCallback(async () => {
    const [latestResult, historyResult, alertResult, sensorResult] = await Promise.allSettled([
      api("/api/sensors/latest"),
      api("/api/sensors/history?limit=120"),
      api("/api/alerts?limit=1000"),
      api("/api/sensors/status"),
    ]);

    let problem = "";
    if (latestResult.status === "fulfilled") {
      if (latestResult.value) applyReading(latestResult.value);
    } else {
      problem = latestResult.reason?.message || "Could not load the latest reading.";
    }
    if (historyResult.status === "fulfilled") {
      setHistory((previous) => mergeHistory(historyResult.value || [], previous));
    } else if (!problem) {
      problem = historyResult.reason?.message || "Could not load the reading history.";
    }
    if (alertResult.status === "fulfilled") setAlerts(alertResult.value);
    if (sensorResult.status === "fulfilled") setSensors(sensorResult.value);
    setError(problem);
  }, [applyReading]);

  useEffect(() => {
    refresh();
    let socket;
    let retryTimer;
    let pollTimer;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      let target;
      try {
        target = safeWebSocketUrl();
      } catch {
        setSocketStatus("disconnected");
        setError("The WebSocket URL in VITE_WS_URL is invalid.");
        return;
      }
      try {
        socket = new WebSocket(target);
      } catch {
        setSocketStatus("disconnected");
        setError(`Could not open the WebSocket at ${target}. Check VITE_WS_URL and the backend address.`);
        return;
      }
      socket.onopen = () => {
        setSocketStatus("connected");
        // Catch up on anything that happened while the socket was closed.
        refresh();
      };
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type !== "reading") return;
          lastMessageAt.current = Date.now();
          applyReading(message.data);
          // Alerts and sensor status change slowly; do not refetch them on
          // every 1 Hz reading.
          refreshAux();
        } catch {
          setError("Received an invalid live update.");
        }
      };
      socket.onclose = () => {
        setSocketStatus("disconnected");
        if (!stopped) retryTimer = window.setTimeout(connect, 2500);
      };
      socket.onerror = () => socket.close();
    };

    const poll = async () => {
      if (stopped) return;
      const socketHealthy = socket
        && socket.readyState === WebSocket.OPEN
        && Date.now() - lastMessageAt.current < LIVE_WINDOW_MS;
      if (socketHealthy) return;
      try {
        const current = await api("/api/sensors/latest");
        if (current) applyReading(current);
        setError("");
      } catch (reason) {
        setError(reason.message);
      }
      refreshAux();
    };

    connect();
    pollTimer = window.setInterval(poll, POLL_MS);

    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      window.clearInterval(pollTimer);
      socket?.close();
    };
  }, [applyReading, refresh, refreshAux]);

  return { latest, history, alerts, sensors, socketStatus, error, lastUpdate, refresh, setError };
}
