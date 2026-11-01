import {
  AlertTriangle,
  ArrowUpRight,
  Camera,
  CheckCircle2,
  Coins,
  ScanLine,
  ShieldCheck,
  Wallet,
} from "lucide-react";
import { withToken } from "../lib/api";
import { formatTime } from "../lib/format";

const number = new Intl.NumberFormat("zh-CN");

const STATUS_META = {
  confirmed: { label: "已确认", tone: "mint" },
  unchanged: { label: "0 变化", tone: "slate" },
  decreased: { label: "余额下降", tone: "rose" },
  missing_balance: { label: "缺余额读数", tone: "amber" },
  missing_screenshot: { label: "缺截图", tone: "amber" },
};

const RUN_META = {
  confirmed: { label: "证据完整", tone: "mint" },
  partial: { label: "缺少截图", tone: "amber" },
  missing: { label: "读数缺失", tone: "amber" },
};

const SECTION_LABELS = {
  daily: "每日",
  weekly: "每周",
  monthly: "每月",
  more: "更多",
  unknown: "其他",
};

function fmt(value) {
  if (value === null || value === undefined) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return number.format(numeric);
}

function signed(value) {
  if (value === null || value === undefined) return "—";
  const numeric = Number(value);
  if (!Number.isFinite(numeric)) return "—";
  return `${numeric > 0 ? "+" : ""}${number.format(numeric)}`;
}

function statusMeta(status) {
  return STATUS_META[status] || { label: "未确认", tone: "slate" };
}

function runMeta(status) {
  return RUN_META[status] || { label: "未确认", tone: "slate" };
}

function ShotLink({ shot, children }) {
  if (!shot?.url) {
    return <span className="evidence-shot-link is-missing">截图缺失</span>;
  }
  return (
    <a
      className="evidence-shot-link"
      href={withToken(shot.url)}
      target="_blank"
      rel="noreferrer"
      title={shot.name || "查看积分证据截图"}
    >
      <Camera size={11} />
      {children || "查看截图"}
    </a>
  );
}

function TaskRow({ task }) {
  const meta = statusMeta(task.status);
  const confirmed = task.status === "confirmed";
  const deltaText = confirmed
    ? `+${fmt(task.delta)}`
    : task.status === "unchanged"
      ? "0"
      : task.status === "decreased"
        ? signed(task.delta)
        : "—";

  return (
    <div className="evidence-task">
      <span className={`evidence-task-dot is-${meta.tone}`} />
      <div className="evidence-task-main">
        <div className="evidence-task-title">
          <strong>{task.label || `任务 ${task.index || ""}`}</strong>
          <span className={`evidence-status is-${meta.tone}`}>{meta.label}</span>
        </div>
        <span className="evidence-task-meta">
          {task.before !== null && task.after !== null
            ? `${fmt(task.before)} → ${fmt(task.after)}`
            : "余额读数不完整"}
          {task.note ? ` · ${task.note}` : ""}
        </span>
        <div className="evidence-task-shots">
          <ShotLink shot={task.before_shot}>开始积分</ShotLink>
          <ShotLink shot={task.after_shot}>结束积分</ShotLink>
        </div>
      </div>
      <span className={`evidence-task-delta is-${meta.tone}`}>{deltaText}</span>
    </div>
  );
}

export default function PointsEvidence({ points, running = false, onOpenGallery }) {
  const data = points || {};
  const remaining = data.remaining || null;
  const balance = data.balance || null;
  const lastRun = data.last_run || null;
  const confirmed = Number(data.today_confirmed) || 0;
  const confirmedTasks = Number(data.today_confirmed_tasks) || 0;
  const unconfirmedTasks = Number(data.today_unconfirmed_tasks) || 0;
  const todayNet =
    data.today_net === null || data.today_net === undefined
      ? null
      : Number(data.today_net);
  const runTasks = Array.isArray(lastRun?.tasks) ? lastRun.tasks : [];
  const runStatus = runMeta(lastRun?.status);
  const sections = remaining?.sections || {};
  const sectionChips = Object.entries(sections)
    .filter(([, value]) => Number(value) > 0)
    .slice(0, 4);

  return (
    <section className="points-evidence">
      <div className="evidence-aurora" aria-hidden="true" />

      <div className="evidence-head">
        <div className="evidence-heading">
          <span className="evidence-kicker">
            <span className={`evidence-live ${running ? "is-live" : ""}`} />
            POINTS EVIDENCE
            <span className="evidence-tag">真实页面读数 · 非估算</span>
          </span>
          <h3>积分实测</h3>
          <p>
            每个任务开始与结束时各留一张账户余额截图；只有两张截图都存在且余额确实增加，
            才把差额计入今日实测。
          </p>
        </div>
        <div className="evidence-today">
          <span>统计日期</span>
          <strong>{data.today || "—"}</strong>
          <small>{running ? "任务运行中，证据实时写入" : "数据只保存在本机"}</small>
        </div>
      </div>

      <div className="evidence-grid">
        <article className="evidence-stat is-remaining">
          <span className="evidence-stat-label">
            <ScanLine size={14} />
            今天还能获得
          </span>
          <div className="evidence-value">
            <strong>{remaining ? fmt(remaining.points) : "—"}</strong>
            <span>分</span>
          </div>
          <span className="evidence-stat-meta">
            {remaining
              ? `页面可见 ${remaining.task_count} 个未完成任务`
              : "运行一次后读取 Rewards 任务页"}
          </span>
          {sectionChips.length ? (
            <div className="evidence-chips">
              {sectionChips.map(([key, value]) => (
                <span className="evidence-chip" key={key}>
                  {SECTION_LABELS[key] || key}
                  <b>+{fmt(value)}</b>
                </span>
              ))}
            </div>
          ) : null}
          <span className="evidence-source">
            {remaining?.at ? `读取于 ${formatTime(remaining.at)}` : "来源：任务卡片 +N 徽标"}
          </span>
        </article>

        <article className="evidence-stat is-confirmed">
          <span className="evidence-stat-label">
            <Coins size={14} />
            今日实测获得
          </span>
          <div className="evidence-value">
            <strong>{confirmed > 0 ? `+${fmt(confirmed)}` : "0"}</strong>
            <span>分</span>
          </div>
          <span className="evidence-stat-meta">
            {confirmedTasks > 0
              ? `${confirmedTasks} 个任务已确认`
              : "还没有可确认的任务收益"}
            {unconfirmedTasks > 0 ? ` · ${unconfirmedTasks} 个未确认` : ""}
          </span>
          {todayNet !== null ? (
            <span className="evidence-net">
              今日余额净变化 <b>{signed(todayNet)}</b>
              <i>含领取、搜索等全部操作</i>
            </span>
          ) : null}
          <span className="evidence-source">
            仅累计开始/结束截图齐全且余额增加的任务
          </span>
        </article>

        <article className="evidence-stat is-balance">
          <span className="evidence-stat-label">
            <Wallet size={14} />
            当前账户余额
          </span>
          <div className="evidence-value">
            <strong>{balance ? fmt(balance.points) : "—"}</strong>
            <span>分</span>
          </div>
          <span className="evidence-stat-meta">
            {balance
              ? `最近读取 ${formatTime(balance.at)}`
              : "运行一次后读取 Rewards 顶栏"}
          </span>
          <div className="evidence-balance-foot">
            <ShotLink shot={balance?.shot}>余额截图</ShotLink>
            <button type="button" className="evidence-gallery-link" onClick={onOpenGallery}>
              证据图库
              <ArrowUpRight size={12} />
            </button>
          </div>
        </article>
      </div>

      <div className="evidence-run">
        <div className="evidence-run-head">
          <div className="evidence-run-title">
            <span className="evidence-run-kicker">
              <ShieldCheck size={13} />
              最近一轮
            </span>
            <strong>
              {lastRun ? formatTime(lastRun.finished_at || lastRun.started_at) : "尚无运行记录"}
            </strong>
            {lastRun ? (
              <span className={`evidence-status is-${runStatus.tone}`}>
                {runStatus.label}
              </span>
            ) : null}
          </div>
          <div className="evidence-run-delta">
            {lastRun && lastRun.before !== null && lastRun.after !== null ? (
              <>
                <span>
                  {fmt(lastRun.before)} → {fmt(lastRun.after)}
                </span>
                <strong className={Number(lastRun.delta) > 0 ? "is-up" : ""}>
                  {signed(lastRun.delta)}
                </strong>
              </>
            ) : (
              <span className="evidence-run-missing">
                <AlertTriangle size={13} />
                余额读数不完整，未推测收益
              </span>
            )}
          </div>
        </div>

        {lastRun ? (
          <div className="evidence-run-facts">
            <span>
              逐任务确认 <b>+{fmt(lastRun.confirmed)}</b> 分
            </span>
            <span>
              未确认 <b>{fmt(lastRun.unconfirmed)}</b> 个
            </span>
            <span className="evidence-run-shots">
              <ShotLink shot={lastRun.start_shot}>开始基线</ShotLink>
              <ShotLink shot={lastRun.end_shot}>结束结算</ShotLink>
            </span>
          </div>
        ) : null}

        {runTasks.length ? (
          <div className="evidence-tasks">
            {runTasks.map((task) => (
              <TaskRow task={task} key={`${task.index}-${task.at}-${task.label}`} />
            ))}
          </div>
        ) : (
          <div className="evidence-empty">
            <CheckCircle2 size={17} />
            <span>
              {lastRun?.mode === "advanced"
                ? "进阶 AI 模式按整轮结算，未拆分为单任务；整轮余额变化见上方。"
                : "运行一次基础任务后，这里会逐条列出任务的开始/结束余额与截图。"}
            </span>
          </div>
        )}
      </div>

      <p className="evidence-note">
        <AlertTriangle size={12} />
        「今天还能获得」只汇总 Rewards 页面未完成任务卡片上的 +N；「今日实测」只累计两张余额截图
        齐全且余额增加的任务。读数或截图缺失时保留“—”，程序不会用本地估值补齐，也不会按积分徽标
        反推任务收益。
      </p>
    </section>
  );
}
