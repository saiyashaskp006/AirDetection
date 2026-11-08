import { useCallback, useEffect, useState } from "react";
import { api, websocketUrl } from "../services/api";

export function useLiveData() {
  const [latest, setLatest] = useState(null);
  const [history, setHistory] = useState([]);
  const [alerts, setAlerts] = useState([]);
  const [sensors, setSensors] = useState([]);
  const [socketStatus, setSocketStatus] = useState("connecting");
  const [error, setError] = useState("");

  const refresh = useCallback(async () => {
    try {
      const [current, rows, alertRows, sensorRows] = await Promise.all([
        api("/api/sensors/latest"),
        api("/api/sensors/history?limit=120"),
        api("/api/alerts?limit=1000"),
        api("/api/sensors/status"),
      ]);
      setLatest(current);
      setHistory(rows);
      setAlerts(alertRows);
      setSensors(sensorRows);
      setError("");
    } catch (reason) {
      setError(reason.message);
    }
  }, []);

  useEffect(() => {
    refresh();
    let socket;
    let retryTimer;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      socket = new WebSocket(websocketUrl());
      socket.onopen = () => setSocketStatus("connected");
      socket.onmessage = (event) => {
        try {
          const message = JSON.parse(event.data);
          if (message.type !== "reading") return;
          setLatest(message.data);
          setHistory((previous) => [...previous, message.data].slice(-120));
          api("/api/alerts?limit=1000").then(setAlerts).catch((reason) => setError(reason.message));
          api("/api/sensors/status").then(setSensors).catch((reason) => setError(reason.message));
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
    connect();
    return () => {
      stopped = true;
      window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [refresh]);

  return { latest, history, alerts, sensors, socketStatus, error, refresh, setError };
}
