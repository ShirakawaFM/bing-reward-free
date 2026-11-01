import { useEffect, useState } from "react";
import { Activity, CalendarClock, Leaf, RefreshCw } from "lucide-react";
import { viewMeta } from "../lib/navigation";
import {
  formatActiveDays,
  formatClock,
  formatDateLine,
  relativeUntil,
} from "../lib/format";
import { Dot } from "./ui";

export default function TopBar({
  view,
  scheduler,
  job,
  loginActive,
  connection,
  power,
  onRefresh,
  refreshing,
}) {
  const [now, setNow] = useState(new Date());
  const meta = viewMeta(view);
  const eco = Boolean(power?.enabled);

  useEffect(() => {
    const timer = window.setInterval(
      () => setNow(new Date()),
      eco ? 15000 : 1000,
    );
    return () => window.clearInterval(timer);
  }, [eco]);

  return (
    <header className="topbar">
      <div className="topbar-heading">
        <div className="topbar-code">
          <span className="code-mark">R/P</span>
          <span>{meta.code}</span>
        </div>
        <h1>{meta.title}</h1>
        <p>{meta.subtitle}</p>
      </div>

      <div className="topbar-tools">
        <div className="clock">
          <span className="clock-time">{formatClock(now)}</span>
          <span className="clock-date">{formatDateLine(now)}</span>
        </div>

        {eco ? (
          <span
            className="status-chip chip-mint chip-eco"
            title={`低功耗挂机已持续 ${formatActiveDays(power.days_active)}`}
          >
            <Leaf size={13} />
            低功耗挂机
          </span>
        ) : null}

        {loginActive ? (
          <span className="status-chip chip-amber">
            <Dot tone="amber" pulse />
            登录窗口
          </span>
        ) : null}

        {job.running ? (
          <span className="status-chip chip-mint">
            <Activity size={13} />
            任务执行中
          </span>
        ) : scheduler.running ? (
          <span className="status-chip chip-mint" title="每日调度运行中">
            <CalendarClock size={13} />
            {relativeUntil(scheduler.next_run)}
          </span>
        ) : (
          <span className="status-chip chip-idle">
            <Dot tone="idle" />
            调度待命
          </span>
        )}

        <button
          type="button"
          className={`icon-btn refresh-btn ${refreshing ? "is-spinning" : ""} ${
            connection !== "online" ? "is-offline" : ""
          }`}
          onClick={onRefresh}
          aria-label="刷新状态"
          title="刷新状态"
          disabled={refreshing}
        >
          <RefreshCw size={17} />
        </button>
      </div>
    </header>
  );
}
