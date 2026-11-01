import { useCallback, useEffect, useRef, useState } from "react";
import { api } from "../lib/api";

export function useAppData() {
  const [state, setState] = useState(null);
  const [connection, setConnection] = useState("connecting");
  const [logs, setLogs] = useState([]);
  const [screenshots, setScreenshots] = useState([]);
  const [shotsLoading, setShotsLoading] = useState(false);
  const lastSeq = useRef(0);
  const ecoRef = useRef(false);

  const refreshState = useCallback(async () => {
    try {
      const data = await api.state();
      setState(data);
      ecoRef.current = Boolean(data.power?.enabled);
      setConnection("online");
      return data;
    } catch (error) {
      setConnection(error.status === 401 ? "unauthorized" : "offline");
      throw error;
    }
  }, []);

  const clearLogs = useCallback(() => setLogs([]), []);

  const refreshScreenshots = useCallback(async () => {
    setShotsLoading(true);
    try {
      const data = await api.screenshots();
      setScreenshots(Array.isArray(data.groups) ? data.groups : []);
    } catch {
      // 状态轮询会负责报告连接问题，这里静默重试。
    } finally {
      setShotsLoading(false);
    }
  }, []);

  useEffect(() => {
    let alive = true;
    let timer = null;

    const loop = async () => {
      try {
        const data = await api.state();
        if (!alive) return;
        setState(data);
        ecoRef.current = Boolean(data.power?.enabled);
        setConnection("online");
      } catch (error) {
        if (!alive) return;
        setConnection(error.status === 401 ? "unauthorized" : "offline");
      }
      if (alive) {
        const interval = document.hidden
          ? 15000
          : ecoRef.current
            ? 8000
            : 2400;
        timer = window.setTimeout(loop, interval);
      }
    };

    loop();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, []);

  useEffect(() => {
    let alive = true;
    let timer = null;

    const loop = async () => {
      if (connection === "online") {
        try {
          const data = await api.logs(lastSeq.current, 800);
          if (!alive) return;
          if (data.last_seq < lastSeq.current) {
            // 后端重启后序号会归零，清空旧缓冲重新同步。
            lastSeq.current = 0;
            setLogs([]);
          } else if (Array.isArray(data.items) && data.items.length) {
            setLogs((current) => {
              const merged = [...current, ...data.items];
              return merged.length > 900 ? merged.slice(-900) : merged;
            });
          }
          if (typeof data.last_seq === "number") lastSeq.current = data.last_seq;
        } catch {
          // 错误由状态轮询统一展示。
        }
      }
      if (alive) {
        const interval = document.hidden
          ? 12000
          : ecoRef.current
            ? 5000
            : 1400;
        timer = window.setTimeout(loop, interval);
      }
    };

    loop();
    return () => {
      alive = false;
      if (timer) window.clearTimeout(timer);
    };
  }, [connection]);

  useEffect(() => {
    refreshScreenshots();
  }, [refreshScreenshots]);

  return {
    state,
    connection,
    logs,
    screenshots,
    shotsLoading,
    refreshState,
    refreshScreenshots,
    clearLogs,
  };
}
