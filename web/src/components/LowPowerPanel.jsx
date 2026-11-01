import { useMemo, useState } from "react";
import {
  AlertTriangle,
  CheckCircle2,
  Gauge,
  Leaf,
  Moon,
  Power,
  RefreshCw,
  ScanLine,
  ShieldCheck,
  Timer,
  Trash2,
} from "lucide-react";
import { Modal, Spinner } from "./ui";
import { api } from "../lib/api";
import { formatActiveDays } from "../lib/format";

function PowerFact({ icon: Icon, label, value, tone = "" }) {
  return (
    <div className={`power-fact ${tone ? `is-${tone}` : ""}`}>
      <span className="power-fact-icon">
        <Icon size={14} />
      </span>
      <span className="power-fact-copy">
        <small>{label}</small>
        <strong>{value}</strong>
      </span>
    </div>
  );
}

export default function LowPowerPanel({
  power = {},
  jobRunning = false,
  onChanged,
  onToast,
}) {
  const [apps, setApps] = useState([]);
  const [scanState, setScanState] = useState("idle");
  const [cleanupOpen, setCleanupOpen] = useState(false);
  const [selected, setSelected] = useState([]);
  const [confirmOpen, setConfirmOpen] = useState(false);
  const [busy, setBusy] = useState(false);

  const enabled = Boolean(power.enabled);
  const supported = power.supported !== false;
  const targetDays = Number(power.target_days) || 7;
  const daysActive = Number(power.days_active) || 0;
  const progress = Math.min(100, (daysActive / targetDays) * 100);
  const cleanupBlocked = enabled || jobRunning;

  const selectedLabels = useMemo(
    () =>
      selected.map((exe) => apps.find((item) => item.exe === exe)?.label || exe),
    [apps, selected],
  );

  const scanApps = async () => {
    setCleanupOpen(true);
    setScanState("loading");
    try {
      const data = await api.powerApps();
      setApps(Array.isArray(data.apps) ? data.apps : []);
      setScanState("ready");
    } catch (error) {
      setScanState("error");
      onToast({ tone: "error", title: "扫描失败", message: error.message });
    }
  };

  const toggleApp = (exe) => {
    setSelected((current) =>
      current.includes(exe)
        ? current.filter((item) => item !== exe)
        : [...current, exe],
    );
  };

  const applyPowerState = (next) => {
    onChanged?.(next);
  };

  const doActivate = async (closeApps) => {
    setBusy(true);
    try {
      const data = await api.powerActivate(closeApps);
      applyPowerState(data.power);
      setConfirmOpen(false);
      setCleanupOpen(false);
      setSelected([]);
      onToast({
        tone: "success",
        title: "低功耗挂机已开启",
        message: "已切换系统节能计划、降低进程优先级并阻止空闲休眠。",
      });
    } catch (error) {
      onToast({ tone: "error", title: "无法开启低功耗", message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const activate = () => {
    if (selected.length) {
      setConfirmOpen(true);
      return;
    }
    doActivate([]);
  };

  const deactivate = async () => {
    setBusy(true);
    try {
      const data = await api.powerDeactivate();
      applyPowerState(data.power);
      onToast({
        tone: "info",
        title: "低功耗挂机已关闭",
        message: "已恢复原来的电源计划与进程优先级。",
      });
    } catch (error) {
      onToast({ tone: "error", title: "无法关闭低功耗", message: error.message });
    } finally {
      setBusy(false);
    }
  };

  const plan = power.power_plan || {};
  const cleanup = Array.isArray(power.cleanup) ? power.cleanup : [];
  const warnings = Array.isArray(power.warnings) ? power.warnings : [];

  return (
    <div className={`power-panel ${enabled ? "is-on" : ""}`}>
      <div className="power-hero">
        <span className={`power-orb ${enabled ? "is-on" : ""}`}>
          <Leaf size={20} />
        </span>
        <div className="power-hero-copy">
          <strong>{enabled ? "低功耗挂机进行中" : "低功耗挂机未开启"}</strong>
          <p>
            {enabled
              ? `已持续 ${formatActiveDays(daysActive)}，目标 ${targetDays} 天。显示器可以关闭，程序会保持唤醒继续等待调度。`
              : `为长时间无人值守设计：节能电源计划 + 最低进程优先级 + EcoQoS，并阻止系统空闲休眠。目标可连续挂机 ${targetDays} 天。`}
          </p>
        </div>
        <span className={`power-state-tag ${enabled ? "is-on" : ""}`}>
          {enabled ? "ECO ON" : "ECO OFF"}
        </span>
      </div>

      {enabled ? (
        <div className="power-progress">
          <div className="power-progress-head">
            <span>挂机进度</span>
            <strong>
              {formatActiveDays(daysActive)} / {targetDays} 天
            </strong>
          </div>
          <div className="power-progress-track">
            <span style={{ width: `${Math.max(1.5, progress)}%` }} />
          </div>
        </div>
      ) : null}

      <div className="power-facts">
        <PowerFact
          icon={Power}
          label={enabled ? "Windows 电源计划" : "当前电源计划"}
          value={plan.active_name || (enabled ? "节能模式" : "保持当前计划")}
          tone={enabled ? "mint" : ""}
        />
        <PowerFact
          icon={Moon}
          label="空闲休眠"
          value={power.hold_awake ? "已阻止（显示器可关闭）" : "未接管"}
          tone={power.hold_awake ? "mint" : ""}
        />
        <PowerFact
          icon={Gauge}
          label="进程效率"
          value={
            power.eco_qos || power.priority_lowered
              ? [
                  power.priority_lowered ? "最低优先级" : "",
                  power.eco_qos ? "EcoQoS" : "",
                ]
                  .filter(Boolean)
                  .join(" · ")
              : "普通"
          }
          tone={power.eco_qos ? "mint" : ""}
        />
        <PowerFact
          icon={Timer}
          label="单实例守护"
          value="同一时间只保留一个 Rewards Pilot"
        />
      </div>

      {enabled && plan.changed ? (
        <p className="power-plan-note">
          <ShieldCheck size={13} />
          退出低功耗时会恢复原电源计划
          {plan.before_name ? `「${plan.before_name}」` : ""}；异常退出后也会在下次启动时恢复。
        </p>
      ) : null}

      {warnings.length ? (
        <div className="power-warnings">
          {warnings.map((item, index) => (
            <p key={`${index}-${item.slice(0, 12)}`}>
              <AlertTriangle size={13} />
              {item}
            </p>
          ))}
        </div>
      ) : null}

      {enabled && cleanup.length ? (
        <div className="power-cleanup-result">
          <span className="power-cleanup-title">本次清理结果</span>
          {cleanup.map((item) => (
            <span className="cleanup-chip" key={item.exe}>
              {item.exe}
              <strong>
                {item.closed}/{item.targets}
              </strong>
            </span>
          ))}
        </div>
      ) : null}

      {!enabled ? (
        <div className="power-cleanup">
          <div className="power-cleanup-head">
            <div>
              <strong>可选：关闭后台应用，进一步减少占用</strong>
              <p>
                只扫描并允许结束白名单中的桌面应用（如聊天、网盘、启动器）。
                系统关键进程、浏览器和 Rewards Pilot 自身永远不会被结束。
              </p>
            </div>
            <button
              type="button"
              className="btn btn-subtle"
              onClick={scanApps}
              disabled={busy || cleanupBlocked || scanState === "loading"}
            >
              {scanState === "loading" ? (
                <Spinner size={14} />
              ) : scanState === "ready" ? (
                <RefreshCw size={14} />
              ) : (
                <ScanLine size={14} />
              )}
              {scanState === "loading"
                ? "扫描中…"
                : scanState === "ready"
                  ? "重新扫描"
                  : "扫描后台应用"}
            </button>
          </div>

          {cleanupBlocked ? (
            <p className="power-cleanup-locked">
              <ShieldCheck size={13} />
              {jobRunning
                ? "任务正在运行，本次开启低功耗不会结束任何应用。"
                : "低功耗已开启，退出后才能执行新的清理。"}
            </p>
          ) : null}

          {cleanupOpen && scanState === "ready" ? (
            apps.length ? (
              <div className="power-app-list">
                {apps.map((app) => {
                  const checked = selected.includes(app.exe);
                  return (
                    <button
                      type="button"
                      key={app.exe}
                      className={`power-app ${checked ? "is-checked" : ""}`}
                      onClick={() => toggleApp(app.exe)}
                      disabled={busy || cleanupBlocked}
                      role="checkbox"
                      aria-checked={checked}
                    >
                      <span className="power-app-check">
                        {checked ? <CheckCircle2 size={14} /> : null}
                      </span>
                      <span className="power-app-copy">
                        <strong>{app.label}</strong>
                        <small>{app.exe}</small>
                      </span>
                      <span className="power-app-meta">
                        {app.count} 个进程 · {Number(app.memory_mb).toFixed(1)} MB
                      </span>
                    </button>
                  );
                })}
                <p className="power-app-note">
                  <Trash2 size={12} />
                  将结束 {selected.length} 个应用；不会使用任意 PID 或系统级批量清理。
                </p>
              </div>
            ) : (
              <p className="power-app-empty">
                没有发现白名单中的后台应用。系统服务、Edge 以及其他进程不会被列入清理。
              </p>
            )
          ) : null}

          {scanState === "error" ? (
            <p className="power-app-empty">扫描失败，可以稍后重试。</p>
          ) : null}
        </div>
      ) : null}

      <div className="power-actions">
        <button
          type="button"
          className={`btn ${enabled ? "btn-subtle" : "btn-primary"}`}
          onClick={enabled ? deactivate : activate}
          disabled={busy || !supported}
        >
          {busy ? <Spinner size={15} /> : enabled ? <Power size={15} /> : <Leaf size={15} />}
          {enabled
            ? busy
              ? "正在恢复…"
              : "退出低功耗，恢复原计划"
            : busy
              ? "正在切换…"
              : "开启低功耗挂机"}
        </button>
        <span className="power-actions-note">
          {supported
            ? enabled
              ? "退出后恢复原电源计划；程序退出时会自动恢复。"
              : "低功耗期间的任务强制使用无头 Edge，不弹出浏览器窗口。"
            : "当前系统不支持 Xbox/Windows 电源接口，仅能使用部分节能能力。"}
        </span>
      </div>

      <p className="power-safety">
        <ShieldCheck size={13} />
        不会断开网络，不会修改 BIOS 或驱动，也不会结束系统必要进程、浏览器或第二个
        Rewards Pilot；单实例互斥锁会阻止重复启动。
      </p>

      <Modal
        open={confirmOpen}
        onClose={() => {
          if (!busy) setConfirmOpen(false);
        }}
        className="confirm-dialog power-confirm"
        labelledBy="power-cleanup-title"
      >
        <div className="confirm-icon">
          <Leaf size={24} />
        </div>
        <h2 id="power-cleanup-title">开启低功耗并清理后台应用？</h2>
        <p>
          将切换到 Windows 节能计划，并结束以下用户应用：
        </p>
        <div className="power-confirm-list">
          {selectedLabels.map((label) => (
            <span key={label}>
              <Trash2 size={12} />
              {label}
            </span>
          ))}
        </div>
        <p>
          系统进程、浏览器、Rewards Pilot 不会被结束。未保存的工作可能丢失，请先确认这些应用可以关闭。
        </p>
        <div className="confirm-actions">
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => setConfirmOpen(false)}
            disabled={busy}
          >
            取消
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={() => doActivate(selected)}
            disabled={busy}
          >
            {busy ? <Spinner size={15} /> : <Leaf size={15} />}
            {busy ? "正在切换…" : "确认开启并清理"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
