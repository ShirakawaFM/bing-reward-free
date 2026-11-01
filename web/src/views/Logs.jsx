import { useMemo, useState } from "react";
import {
  Copy,
  Eraser,
  Search,
  Terminal,
  X,
} from "lucide-react";
import LogConsole from "../components/LogConsole";
import { Switch } from "../components/ui";
import { levelLabel, levelRank } from "../lib/format";

const FILTERS = [
  { id: "all", label: "全部" },
  { id: "info", label: "INFO" },
  { id: "warn", label: "WARN" },
  { id: "error", label: "ERROR" },
];

export default function Logs({ logs, onClear, onToast }) {
  const [filter, setFilter] = useState("all");
  const [query, setQuery] = useState("");
  const [autoScroll, setAutoScroll] = useState(true);

  const counts = useMemo(() => {
    let info = 0;
    let warn = 0;
    let error = 0;
    for (const item of logs) {
      const rank = levelRank(item.level);
      if (rank >= 40) error += 1;
      else if (rank >= 30) warn += 1;
      else if (rank >= 20) info += 1;
    }
    return { all: logs.length, info, warn, error };
  }, [logs]);

  const filtered = useMemo(() => {
    const keyword = query.trim().toLowerCase();
    return logs.filter((item) => {
      const rank = levelRank(item.level);
      if (filter === "info" && (rank < 20 || rank >= 30)) return false;
      if (filter === "warn" && (rank < 30 || rank >= 40)) return false;
      if (filter === "error" && rank < 40) return false;
      if (!keyword) return true;
      return [item.message, item.name, item.level]
        .join(" ")
        .toLowerCase()
        .includes(keyword);
    });
  }, [logs, filter, query]);

  const copyLogs = async () => {
    if (!filtered.length) return;
    const text = filtered
      .map(
        (item) =>
          `${item.time} | ${levelLabel(item.level).padEnd(5)} | ${item.name} | ${item.message}`,
      )
      .join("\n");
    try {
      await navigator.clipboard.writeText(text);
      onToast({
        tone: "success",
        title: "日志已复制",
        message: `已复制 ${filtered.length} 条到剪贴板。`,
      });
    } catch {
      onToast({
        tone: "error",
        title: "复制失败",
        message: "浏览器拒绝了剪贴板访问，请手动选择文本复制。",
      });
    }
  };

  return (
    <div className="view logs-view">
      <section className="card logs-panel">
        <div className="logs-head">
          <div className="head-title">
            <span className="head-glyph is-mint">
              <Terminal size={18} />
            </span>
            <div>
              <h2>执行轨迹</h2>
              <p>任务扫描、模型决策、点击与领取，都会按时间顺序落在这里。</p>
            </div>
          </div>
          <span className="status-chip chip-mint">
            <span className="live-ring" />
            实时同步
          </span>
        </div>

        <div className="logs-toolbar">
          <div className="log-filters" role="group" aria-label="日志级别筛选">
            {FILTERS.map((item) => {
              const active = filter === item.id;
              return (
                <button
                  key={item.id}
                  type="button"
                  className={`filter-chip ${active ? "is-active" : ""} filter-${item.id}`}
                  onClick={() => setFilter(item.id)}
                >
                  {item.label}
                  <span>{counts[item.id]}</span>
                </button>
              );
            })}
          </div>

          <div className="logs-tools">
            <label className="search-box">
              <Search size={15} />
              <input
                type="search"
                value={query}
                onChange={(event) => setQuery(event.target.value)}
                placeholder="搜索日志…"
                aria-label="搜索日志"
              />
              {query ? (
                <button
                  type="button"
                  className="search-clear"
                  onClick={() => setQuery("")}
                  aria-label="清除搜索"
                >
                  <X size={13} />
                </button>
              ) : null}
            </label>

            <div className="auto-scroll">
              <span>自动滚动</span>
              <Switch
                checked={autoScroll}
                onChange={setAutoScroll}
                label="自动滚动日志"
              />
            </div>

            <button
              type="button"
              className="icon-btn tool-btn"
              onClick={copyLogs}
              title="复制当前日志"
              aria-label="复制当前日志"
              disabled={!filtered.length}
            >
              <Copy size={16} />
            </button>
            <button
              type="button"
              className="icon-btn tool-btn"
              onClick={onClear}
              title="清空界面日志"
              aria-label="清空界面日志"
              disabled={!logs.length}
            >
              <Eraser size={16} />
            </button>
          </div>
        </div>

        <LogConsole
          logs={filtered}
          autoScroll={autoScroll}
          emptyTitle={query || filter !== "all" ? "没有匹配的日志" : "还没有日志"}
          emptyHint={
            query || filter !== "all"
              ? "换一个关键词或级别试试，日志每 1.4 秒自动拉取一次。"
              : "运行任务后，这里会显示完整执行轨迹。"
          }
        />

        <div className="logs-foot">
          <span>
            显示 <strong>{filtered.length}</strong> / {logs.length} 条 · 界面缓存最近 1200 条
          </span>
          <span>完整日志同时写入 logs/rewards_bot.log</span>
        </div>
      </section>

      <div className="logs-hint">
        <span className="hint-mark">TIP</span>
        <p>
          自动搜索与领取均在页面可见时进行。遇到验证码或风控提示时，请手动接管浏览器，
          程序不会尝试绕过人机验证。
        </p>
      </div>
    </div>
  );
}
