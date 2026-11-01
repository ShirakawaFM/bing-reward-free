import { useEffect, useRef, useState } from "react";
import { ArrowDown, Terminal } from "lucide-react";
import { formatTime, levelLabel, shortLogger } from "../lib/format";

export default function LogConsole({
  logs,
  compact = false,
  autoScroll = true,
  emptyTitle = "还没有日志",
  emptyHint = "运行任务后，这里的执行轨迹会实时刷新。",
}) {
  const viewportRef = useRef(null);
  const [pinned, setPinned] = useState(true);

  useEffect(() => {
    const element = viewportRef.current;
    if (!element) return;
    if (autoScroll && pinned) element.scrollTop = element.scrollHeight;
  }, [logs, autoScroll, pinned]);

  useEffect(() => {
    if (logs.length === 0) setPinned(true);
  }, [logs.length]);

  const handleScroll = () => {
    const element = viewportRef.current;
    if (!element) return;
    const nearBottom =
      element.scrollHeight - element.scrollTop - element.clientHeight < 48;
    setPinned(nearBottom);
  };

  const jumpToLatest = () => {
    const element = viewportRef.current;
    if (element) element.scrollTop = element.scrollHeight;
    setPinned(true);
  };

  return (
    <div className={`log-console ${compact ? "is-compact" : ""}`}>
      <div className="log-viewport" ref={viewportRef} onScroll={handleScroll}>
        {logs.length === 0 ? (
          <div className="log-empty">
            <span className="log-empty-icon">
              <Terminal size={22} />
            </span>
            <strong>{emptyTitle}</strong>
            <p>{emptyHint}</p>
          </div>
        ) : (
          logs.map((item) => {
            const level = String(item.level || "info").toLowerCase();
            const levelClass =
              level === "warning" || level === "warn" ? "warn" : level;
            return (
              <div className={`log-line level-${levelClass}`} key={item.seq}>
                <span className="log-time">{formatTime(item.time)}</span>
                <span className={`log-level ${levelClass}`}>
                  {levelLabel(item.level)}
                </span>
                <span className="log-name">{shortLogger(item.name)}</span>
                <span className="log-message">{item.message}</span>
              </div>
            );
          })
        )}
      </div>
      {autoScroll && !pinned && logs.length > 0 ? (
        <button type="button" className="log-jump" onClick={jumpToLatest}>
          <ArrowDown size={14} />
          回到最新
        </button>
      ) : null}
    </div>
  );
}
