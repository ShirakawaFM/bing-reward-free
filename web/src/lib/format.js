const LEVEL_LABELS = {
  debug: "DEBUG",
  info: "INFO",
  warning: "WARN",
  warn: "WARN",
  error: "ERROR",
  critical: "FATAL",
};

export function levelLabel(level) {
  return LEVEL_LABELS[String(level || "").toLowerCase()] || String(level || "").toUpperCase();
}

export function levelRank(level) {
  switch (String(level || "").toLowerCase()) {
    case "debug":
      return 10;
    case "info":
      return 20;
    case "warning":
    case "warn":
      return 30;
    case "error":
      return 40;
    case "critical":
      return 50;
    default:
      return 20;
  }
}

export function formatTime(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatClock(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  }).format(date);
}

export function formatDateLine(value = new Date()) {
  const date = value instanceof Date ? value : new Date(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "long",
    day: "numeric",
    weekday: "long",
  }).format(date);
}

export function formatDateTime(value, timezone) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  try {
    return new Intl.DateTimeFormat("zh-CN", {
      timeZone: timezone || undefined,
      month: "2-digit",
      day: "2-digit",
      hour: "2-digit",
      minute: "2-digit",
      hour12: false,
    }).format(date);
  } catch {
    return date.toLocaleString("zh-CN");
  }
}

export function formatShortDate(value) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return new Intl.DateTimeFormat("zh-CN", {
    month: "2-digit",
    day: "2-digit",
  }).format(date);
}

export function relativeUntil(value) {
  if (!value) return "未排程";
  const target = new Date(value).getTime();
  if (Number.isNaN(target)) return "未排程";
  const diff = target - Date.now();
  if (diff <= 0) return "即将开始";
  const minutes = Math.ceil(diff / 60000);
  if (minutes < 60) return `${minutes} 分钟后`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) {
    const rest = minutes % 60;
    return rest ? `${hours} 小时 ${rest} 分后` : `${hours} 小时后`;
  }
  const days = Math.floor(hours / 24);
  const restHours = hours % 24;
  return restHours ? `${days} 天 ${restHours} 小时后` : `${days} 天后`;
}

export function durationBetween(start, end) {
  if (!start) return null;
  const from = new Date(start).getTime();
  const to = end ? new Date(end).getTime() : Date.now();
  if (Number.isNaN(from) || Number.isNaN(to) || to < from) return null;
  const seconds = Math.round((to - from) / 1000);
  if (seconds < 60) return `${seconds} 秒`;
  const minutes = Math.floor(seconds / 60);
  const rest = seconds % 60;
  return rest ? `${minutes} 分 ${rest} 秒` : `${minutes} 分钟`;
}

export function formatActiveDays(days) {
  const value = Math.max(0, Number(days) || 0);
  if (value <= 0) return "0 分钟";
  const minutes = Math.round(value * 1440);
  if (minutes < 60) return `${Math.max(1, minutes)} 分钟`;
  const hours = value * 24;
  if (hours < 24) return `${hours.toFixed(1)} 小时`;
  const wholeDays = Math.floor(hours / 24);
  const restHours = Math.round(hours % 24);
  return restHours ? `${wholeDays} 天 ${restHours} 小时` : `${wholeDays} 天`;
}

export function formatBytes(bytes) {
  const size = Number(bytes) || 0;
  if (size < 1024) return `${size} B`;
  if (size < 1024 * 1024) return `${(size / 1024).toFixed(0)} KB`;
  return `${(size / 1024 / 1024).toFixed(1)} MB`;
}

const SHOT_LABELS = [
  ["login-success", "登录成功"],
  ["login", "登录现场"],
  ["dashboard", "任务页"],
  ["summary", "任务总览"],
  ["task", "任务页面"],
  ["quiz", "问答现场"],
  ["claim", "领取奖励"],
  ["agent", "AI 决策"],
  ["blocked", "护栏拦截"],
  ["error", "异常现场"],
];

export function shotLabel(name) {
  const base = String(name || "").replace(/\.png$/i, "");
  const lower = base.toLowerCase();
  if (lower === "points-run-start") return "积分基线";
  if (lower === "points-run-end") return "积分结算";
  if (lower.startsWith("points-task-")) {
    if (lower.endsWith("-before")) return "任务前积分";
    if (lower.endsWith("-after")) return "任务后积分";
    return "任务积分证据";
  }
  for (const [prefix, label] of SHOT_LABELS) {
    if (lower.startsWith(prefix)) return label;
  }
  return base.replace(/[-_]+/g, " ").slice(0, 28) || "运行截图";
}

export function shortLogger(name) {
  return String(name || "app")
    .replace(/^rewards_bot\./, "")
    .replace(/^gui\./, "ui.")
    .replace("scheduler", "schedule")
    .replace("settings", "config");
}
