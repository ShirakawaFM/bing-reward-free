import { motion } from "framer-motion";
import { CalendarClock, RadioTower, ShieldCheck, Wifi, WifiOff, Zap } from "lucide-react";
import { NAV_ITEMS } from "../lib/navigation";
import { formatDateTime, relativeUntil } from "../lib/format";
import { Dot } from "./ui";

export default function Sidebar({
  view,
  onNavigate,
  scheduler,
  connection,
  version,
  loginActive,
}) {
  const online = connection === "online";

  return (
    <>
      <aside className="sidebar">
        <button
          type="button"
          className="brand"
          onClick={() => onNavigate("overview")}
          aria-label="返回总览"
        >
          <span className="brand-mark">
            <Zap size={21} strokeWidth={2.4} />
            <span className="brand-glow" />
          </span>
          <span className="brand-copy">
            <strong>
              Rewards <em>Pilot</em>
            </strong>
            <small>LOCAL AUTOMATION</small>
          </span>
        </button>

        <div className="sidebar-label">工作台</div>
        <nav className="side-nav" aria-label="主导航">
          {NAV_ITEMS.map((item) => {
            const Icon = item.icon;
            const active = item.id === view;
            return (
              <button
                key={item.id}
                type="button"
                className={`nav-item ${active ? "is-active" : ""}`}
                onClick={() => onNavigate(item.id)}
                aria-current={active ? "page" : undefined}
              >
                {active ? (
                  <motion.span
                    layoutId="nav-active"
                    className="nav-active-bg"
                    transition={{ type: "spring", stiffness: 420, damping: 36 }}
                  />
                ) : null}
                <span className="nav-icon">
                  <Icon size={18} />
                </span>
                <span className="nav-text">{item.label}</span>
                {item.id === "logs" && loginActive ? (
                  <span className="nav-live-dot" title="登录窗口进行中" />
                ) : null}
              </button>
            );
          })}
        </nav>

        <div className="sidebar-spacer" />

        <div className="side-plan">
          <div className="side-plan-head">
            <span className={`side-orb ${scheduler.running ? "is-on" : ""}`}>
              <CalendarClock size={16} />
            </span>
            <div>
              <strong>{scheduler.running ? "自动巡航中" : "自动巡航暂停"}</strong>
              <small>{scheduler.running ? scheduler.run_at : "尚未开启调度"}</small>
            </div>
          </div>
          {scheduler.running ? (
            <p>
              下次运行
              <span>{relativeUntil(scheduler.next_run)}</span>
            </p>
          ) : (
            <p>开启后程序会在每天固定时间自动完成积分任务。</p>
          )}
          <div className="side-plan-foot">
            <Dot tone={scheduler.running ? "mint" : "idle"} pulse={scheduler.running} />
            <span>
              {scheduler.running
                ? formatDateTime(scheduler.next_run, scheduler.timezone)
                : "可在总览页开启"}
            </span>
          </div>
        </div>

        <div className="side-safe">
          <ShieldCheck size={15} />
          <span>只领取，不兑换 · 本地沙箱</span>
        </div>

        <div className="side-foot">
          <span className={`side-connection ${online ? "is-on" : ""}`}>
            {online ? <Wifi size={14} /> : <WifiOff size={14} />}
            {online ? "本地服务在线" : "连接中断"}
          </span>
          <span className="side-version">v{version}</span>
        </div>
      </aside>

      <nav className="mobile-nav" aria-label="移动端导航">
        {NAV_ITEMS.map((item) => {
          const Icon = item.icon;
          const active = item.id === view;
          return (
            <button
              key={item.id}
              type="button"
              className={active ? "is-active" : ""}
              onClick={() => onNavigate(item.id)}
              aria-current={active ? "page" : undefined}
            >
              <Icon size={19} />
              <span>{item.label}</span>
              {active ? <span className="mobile-nav-dot" /> : null}
            </button>
          );
        })}
      </nav>
    </>
  );
}
