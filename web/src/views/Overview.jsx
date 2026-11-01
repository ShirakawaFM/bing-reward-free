import {
  Activity,
  AlertTriangle,
  CalendarClock,
  CheckCircle2,
  ChevronRight,
  Clock3,
  Images,
  KeyRound,
  Leaf,
  Loader2,
  LockKeyhole,
  LogIn,
  Monitor,
  Play,
  ShieldCheck,
  Sparkles,
  Terminal,
  UserRound,
  Zap,
} from "lucide-react";
import { Segmented, Switch } from "../components/ui";
import Orbit from "../components/Orbit";
import LogConsole from "../components/LogConsole";
import PointsForecast from "../components/PointsForecast";
import { ShotThumb } from "../components/Shots";
import {
  durationBetween,
  formatActiveDays,
  formatDateTime,
  formatShortDate,
  formatTime,
  relativeUntil,
} from "../lib/format";

export default function Overview({
  state,
  logs,
  screenshots,
  mode,
  onModeChange,
  onRun,
  onLogin,
  onToggleScheduler,
  onNavigate,
  busy,
  power = {},
}) {
  const summary = state.summary || {};
  const job = state.job || {};
  const login = state.login || {};
  const scheduler = state.scheduler || {};
  const running = Boolean(job.running);
  const loginActive = Boolean(login.active);
  const schedRunning = Boolean(scheduler.running);
  const eco = Boolean(power.enabled);
  const runAt = scheduler.run_at || summary.run_at || "--:--";
  const apiKeySet = Boolean(summary.api_key_set);

  const previewLogs = (() => {
    const important = logs.filter((item) => item.level !== "debug");
    const source = important.length ? important : logs;
    return source.slice(-10);
  })();

  const recentShots = screenshots.flatMap((group) =>
    group.files.map((file) => ({ ...file, run: group.run })),
  );

  const jobTone = running
    ? "live"
    : job.state === "success"
      ? "ok"
      : job.state === "error"
        ? "error"
        : "idle";

  const jobLabel = running
    ? "执行中"
    : job.state === "success"
      ? "上次成功"
      : job.state === "error"
        ? "上次有异常"
        : "等待首次运行";

  const duration = durationBetween(job.started_at, job.finished_at);
  const statusHeadline = running
    ? "正在执行自动化任务"
    : job.finished_at
      ? job.message || "任务已结束"
      : "控制台已就绪，随时可以起飞。";

  const stats = [
    {
      icon: CalendarClock,
      tone: "mint",
      label: "每日调度",
      value: schedRunning ? `每天 ${runAt}` : "调度已暂停",
      meta: schedRunning
        ? `下次 ${relativeUntil(scheduler.next_run)}`
        : "随时可以重新开启",
    },
    {
      icon: Activity,
      tone: jobTone === "error" ? "rose" : jobTone === "ok" ? "mint" : "sky",
      label: "最近状态",
      value: jobLabel,
      meta: job.finished_at
        ? `${formatShortDate(job.finished_at)} ${formatTime(job.finished_at)}`
        : "还没有运行记录",
    },
    {
      icon: summary.mode === "advanced" ? Sparkles : ShieldCheck,
      tone: "violet",
      label: "默认模式",
      value: summary.mode === "advanced" ? "进阶 · AI" : "基础 · 规则",
      meta:
        summary.mode === "advanced"
          ? summary.model || "DeepSeek"
          : "不调用大模型",
    },
    {
      icon: Monitor,
      tone: "sky",
      label: "浏览器",
      value: summary.browser_channel || "内置 Chromium",
      meta: summary.headless ? "无头运行" : "Edge 窗口可见",
    },
  ];

  const loginHeadline = loginActive
    ? login.state === "checking"
      ? "正在核验登录状态"
      : "登录窗口已打开"
    : login.state === "success"
      ? "登录态已保存"
      : "需要时再验证账号";

  const loginText = loginActive
    ? login.message || "请在弹出的 Edge 窗口完成登录。"
    : login.state === "success"
      ? "浏览器资料已写入本机，下一次运行可以直接复用。"
      : "登录过程完全发生在微软页面，程序不读取密码。";

  return (
    <div className="view overview-view">
      <section className="hero">
        <div className="hero-noise" aria-hidden="true" />
        <div className="hero-copy">
          <div className="hero-badge">
            <span className="badge-pulse" />
            LOCAL-FIRST AUTOMATION
            <span className="badge-divider" />
            <span className="badge-mono">EDGE + PLAYWRIGHT</span>
          </div>

          <h2 className="hero-title">
            把每日积分，
            <br />
            <span className="gradient-text">交给自动巡航。</span>
          </h2>

          <p className="hero-lede">
            自动打开 Rewards 仪表盘，识别每日任务，完成问答并领取奖励。
            基础规则模式开箱即用，进阶模式让 DeepSeek 基于元素索引做出下一步决策。
          </p>

          <div className="hero-actions">
            <button
              type="button"
              className={`btn btn-primary btn-lg ${running ? "is-live" : ""}`}
              onClick={() => onRun(mode)}
              disabled={busy.run || running || loginActive}
            >
              {busy.run || running ? (
                <Loader2 size={18} className="spin" />
              ) : (
                <Play size={18} fill="currentColor" />
              )}
              {running ? "任务正在执行" : busy.run ? "正在启动…" : "立即运行"}
              {!running && !busy.run ? (
                <span className="btn-tail">{mode === "basic" ? "BASIC" : "AI"}</span>
              ) : null}
            </button>

            <button type="button" className="btn btn-ghost btn-lg" onClick={onLogin}>
              <LogIn size={18} />
              {loginActive ? "查看登录进度" : "登录 Microsoft"}
            </button>
          </div>

          <div className="hero-meta">
            <Segmented
              value={mode}
              onChange={onModeChange}
              disabled={running || busy.run}
              options={[
                { value: "basic", label: "基础模式", icon: ShieldCheck },
                { value: "advanced", label: "进阶 AI", icon: Sparkles },
              ]}
            />
            <span className="hero-meta-divider" />
            <button
              type="button"
              className={`key-hint ${mode === "advanced" && !apiKeySet ? "is-warn" : ""}`}
              onClick={() => onNavigate("settings")}
            >
              <KeyRound size={13} />
              {mode === "advanced"
                ? apiKeySet
                  ? "API Key 已就绪"
                  : "进阶模式需要 API Key"
                : "无需 API Key"}
              <ChevronRight size={13} />
            </button>
            <span className="hero-meta-note">本次运行</span>
          </div>

          {eco ? (
            <div className="eco-ribbon">
              <span className="eco-ribbon-icon">
                <Leaf size={14} />
              </span>
              <div className="eco-ribbon-copy">
                <strong>低功耗挂机中</strong>
                <span>
                  已持续 {formatActiveDays(power.days_active)} / 目标{" "}
                  {power.target_days || 7} 天 · 任务强制无头运行
                </span>
              </div>
              <button type="button" onClick={() => onNavigate("settings")}>
                管理
              </button>
            </div>
          ) : null}
        </div>

        <div className="hero-visual">
          <Orbit running={running} schedulerRunning={schedRunning} mode={mode} />
        </div>
      </section>

      <PointsForecast
        forecast={summary.points_forecast}
        mode={mode}
        onImprove={() => onNavigate("settings", { focus: "tasks" })}
      />

      <div className="stat-grid">
        {stats.map((item, index) => {
          const Icon = item.icon;
          return (
            <article className={`stat-card tone-${item.tone}`} key={item.label}>
              <div className="stat-top">
                <span className="stat-icon">
                  <Icon size={17} />
                </span>
                <span className="stat-label">{item.label}</span>
                <span className="stat-index">0{index + 1}</span>
              </div>
              <strong className="stat-value">{item.value}</strong>
              <span className="stat-meta">{item.meta}</span>
            </article>
          );
        })}
      </div>

      <div className="overview-grid">
        <section className="card console-card">
          {running ? <span className="progress-rail is-running" /> : null}
          <div className="card-head">
            <div className="head-title">
              <span className="head-glyph">
                <Terminal size={18} />
              </span>
              <div>
                <h3>运行控制台</h3>
                <p>{statusHeadline}</p>
              </div>
            </div>
            <span className={`status-pill ${jobTone}`}>
              <span className="status-pill-dot" />
              {jobLabel}
            </span>
          </div>

          <div className="console-facts">
            <div>
              <span>执行模式</span>
              <strong>{job.mode === "advanced" || (!job.mode && mode === "advanced") ? "进阶 AI" : "基础规则"}</strong>
            </div>
            <div>
              <span>触发方式</span>
              <strong>{job.trigger === "schedule" ? "每日调度" : job.finished_at || job.started_at ? "手动运行" : "—"}</strong>
            </div>
            <div>
              <span>开始时间</span>
              <strong>{job.started_at ? formatTime(job.started_at) : "—"}</strong>
            </div>
            <div>
              <span>耗时</span>
              <strong>{duration || (running ? "计时中" : "—")}</strong>
            </div>
          </div>

          {!running && job.finished_at && job.state === "error" ? (
            <div className="inline-alert is-error">
              <AlertTriangle size={15} />
              <span>{job.message || "上次运行未完全成功，请查看日志定位原因。"}</span>
            </div>
          ) : null}

          <LogConsole
            logs={previewLogs}
            compact
            autoScroll
            emptyTitle="控制台静候第一条指令"
            emptyHint="点击「立即运行」，实时的任务扫描、问答与领取轨迹会出现在这里。"
          />

          <div className="card-foot">
            <span className="foot-note">
              <span className="foot-live-dot" />
              实时同步 · 最近 {previewLogs.length} 条
            </span>
            <button
              type="button"
              className="link-btn"
              onClick={() => onNavigate("logs")}
            >
              打开完整日志
              <ChevronRight size={15} />
            </button>
          </div>
        </section>

        <div className="side-stack">
          <section className="card side-card plan-card">
            <div className="side-card-head">
              <span className="head-glyph is-mint">
                <CalendarClock size={17} />
              </span>
              <div>
                <h3>每日计划</h3>
                <p>{schedRunning ? "自动巡航已开启" : "自动巡航已暂停"}</p>
              </div>
              <Switch
                checked={schedRunning}
                onChange={() => onToggleScheduler(!schedRunning)}
                disabled={busy.scheduler}
                label="切换每日调度"
              />
            </div>

            <div className="plan-clock">
              <span className={`plan-time ${!schedRunning ? "is-muted" : ""}`}>
                {runAt}
              </span>
              <span className="plan-zone">{summary.timezone || scheduler.timezone || "本地时区"}</span>
            </div>

            <div className="plan-next">
              <Clock3 size={15} />
              {schedRunning ? (
                <span>
                  下次执行 <strong>{relativeUntil(scheduler.next_run)}</strong>
                </span>
              ) : (
                <span>开启后每天 {runAt} 自动运行</span>
              )}
            </div>

            <div className="plan-meta">
              <span>
                补跑
                <strong>{summary.catch_up ? "开启" : "关闭"}</strong>
              </span>
              <span>
                自动领取
                <strong>{summary.auto_claim ? "开启" : "关闭"}</strong>
              </span>
            </div>

            {schedRunning && scheduler.next_run ? (
              <p className="plan-date">
                下一次 · {formatDateTime(scheduler.next_run, scheduler.timezone)}
              </p>
            ) : (
              <p className="plan-date">程序需要保持运行，到点后自动打开浏览器。</p>
            )}
          </section>

          <section className="card side-card account-card">
            <div className="side-card-head">
              <span className={`head-glyph ${loginActive ? "is-amber" : "is-violet"}`}>
                <UserRound size={17} />
              </span>
              <div>
                <h3>Microsoft 账号</h3>
                <p>{loginHeadline}</p>
              </div>
              <span className={`mini-status ${loginActive ? "is-wait" : login.state === "success" ? "is-ok" : ""}`}>
                {loginActive ? "进行中" : login.state === "success" ? "已保存" : "待命"}
              </span>
            </div>
            <p className="account-copy">{loginText}</p>
            <button
              type="button"
              className="btn btn-subtle btn-block"
              onClick={onLogin}
              disabled={Boolean(job.running)}
            >
              {loginActive ? <Loader2 size={16} className="spin" /> : <LogIn size={16} />}
              {loginActive ? "继续登录" : login.state === "success" ? "重新验证登录" : "打开登录窗口"}
            </button>
          </section>

          <section className="safety-card">
            <div className="safety-head">
              <LockKeyhole size={15} />
              安全护栏已启用
            </div>
            <ul>
              <li>
                <CheckCircle2 size={13} />
                只点击「领取」，绝不自动兑换积分
              </li>
              <li>
                <CheckCircle2 size={13} />
                站外链接与支付类操作自动拦截
              </li>
              <li>
                <CheckCircle2 size={13} />
                自动搜索默认关闭，降低风控风险
              </li>
            </ul>
            <span className="safety-foot">
              <ShieldCheck size={13} />
              所有数据都留在本机
            </span>
          </section>
        </div>
      </div>

      <section className="recent-shots">
        <div className="section-head">
          <div className="section-title">
            <span className="head-glyph is-sky">
              <Images size={17} />
            </span>
            <div>
              <h3>最近现场</h3>
              <p>关键页面自动截图，出问题时可以回看每一步。</p>
            </div>
          </div>
          <button type="button" className="link-btn" onClick={() => onNavigate("gallery")}>
            全部截图
            <ChevronRight size={15} />
          </button>
        </div>

        {recentShots.length ? (
          <div className="shot-grid shot-grid-recent">
            {recentShots.slice(0, 4).map((shot) => (
              <ShotThumb
                key={`${shot.run}-${shot.name}`}
                shot={shot}
                onOpen={() => onNavigate("gallery")}
              />
            ))}
          </div>
        ) : (
          <div className="empty-strip">
            <span className="empty-strip-icon">
              <Images size={20} />
            </span>
            <div>
              <strong>还没有运行截图</strong>
              <p>第一次任务结束后，仪表盘、问答页和领取结果会自动留档。</p>
            </div>
            <span className="empty-strip-tag">
              <Zap size={13} />
              自动生成
            </span>
          </div>
        )}
      </section>
    </div>
  );
}
