import { useEffect, useRef } from "react";
import { Check, Lock, MousePointerClick, Sparkles } from "lucide-react";

const SUPPORT_ICON = {
  ai: Sparkles,
  manual: Lock,
};

function TaskRow({ item, checked, supportLabel, onToggle }) {
  const locked = item.support !== "basic";
  const SupportIcon = SUPPORT_ICON[item.support];

  return (
    <button
      type="button"
      className={`task-item is-${item.support} ${checked ? "is-checked" : ""} ${
        locked ? "is-locked" : ""
      }`}
      data-task-id={item.id}
      onClick={() => {
        if (!locked) onToggle(item);
      }}
      disabled={locked}
      role="checkbox"
      aria-checked={checked}
      aria-disabled={locked}
      title={item.description}
    >
      <span className={`task-check ${locked ? "is-locked" : ""}`}>
        {checked ? (
          <Check size={12} strokeWidth={3} />
        ) : locked ? (
          <SupportIcon size={11} />
        ) : (
          <MousePointerClick size={10} />
        )}
      </span>
      <span className="task-copy">
        <span className="task-title">
          {item.label}
          {item.support === "basic" && item.default ? (
            <em className="task-recommended">推荐</em>
          ) : null}
        </span>
        <span className="task-description">{item.description}</span>
        {item.caution ? <span className="task-caution">{item.caution}</span> : null}
      </span>
      {locked ? (
        <span className={`task-support is-${item.support}`}>{supportLabel}</span>
      ) : item.field ? (
        <span className="task-support is-action">动作</span>
      ) : null}
    </button>
  );
}

export default function TaskPicker({
  catalog,
  selectedIds,
  autoClaim,
  searchEnabled,
  focusRequest = null,
  onToggle,
  onSelectAll,
  onRecommend,
  disabled = false,
}) {
  const rootRef = useRef(null);

  useEffect(() => {
    if (!focusRequest || !catalog) return undefined;
    const root = rootRef.current;
    if (!root) return undefined;

    const targets = Array.from(
      root.querySelectorAll(".task-item:not(.is-locked):not(.is-checked)"),
    );
    targets.forEach((item) => item.classList.add("is-spotlight"));

    const scrollTimer = window.setTimeout(() => {
      const first = targets[0];
      if (first && first.isConnected) {
        first.scrollIntoView({ behavior: "smooth", block: "center" });
      }
    }, 380);
    const clearTimer = window.setTimeout(() => {
      targets.forEach((item) => item.classList.remove("is-spotlight"));
    }, 7200);

    return () => {
      window.clearTimeout(scrollTimer);
      window.clearTimeout(clearTimer);
      targets.forEach((item) => item.classList.remove("is-spotlight"));
    };
  }, [focusRequest, catalog]);

  if (!catalog) return null;

  const selected = new Set(selectedIds || []);
  const basicCardCount = catalog.basic_card_task_ids.length;
  const chosenCount = catalog.basic_card_task_ids.filter((id) =>
    selected.has(id),
  ).length;
  const labels = catalog.support_labels || {};

  return (
    <div className={`task-picker ${disabled ? "is-disabled" : ""}`} ref={rootRef}>
      <div className="task-picker-head">
        <div className="task-picker-copy">
          <strong>基础模式任务清单</strong>
          <p>
            只勾选你希望自动处理的卡片类型。未勾选的卡片会被跳过，并写入日志。
          </p>
        </div>
        <div className="task-picker-tools">
          <span className="task-picker-count">
            {chosenCount}
            <i>/</i>
            {basicCardCount}
          </span>
          <button
            type="button"
            className="link-btn"
            onClick={onSelectAll}
            disabled={disabled}
          >
            全选
          </button>
          <button
            type="button"
            className="link-btn"
            onClick={onRecommend}
            disabled={disabled}
          >
            恢复推荐
          </button>
        </div>
      </div>

      <div className="task-legend">
        <span className="task-legend-item">
          <span className="legend-mark is-basic" />
          可勾选 · 内置规则
        </span>
        <span className="task-legend-item">
          <Sparkles size={11} />
          仅进阶 AI · 当前不可勾选
        </span>
        <span className="task-legend-item">
          <Lock size={11} />
          需人工处理 · 程序不会执行
        </span>
      </div>

      <div className="task-groups">
        {catalog.groups.map((group) => {
          const items = catalog.items.filter((item) => item.group === group.id);
          const selectable = items.filter((item) => item.support === "basic");
          const activeCount = selectable.filter((item) => {
            if (item.field === "auto_claim") return autoClaim;
            if (item.field === "search_enabled") return searchEnabled;
            return selected.has(item.id);
          }).length;

          return (
            <section className="task-group" key={group.id}>
              <div className="task-group-head">
                <span className="task-group-title">{group.label}</span>
                <span className="task-group-hint">{group.hint}</span>
                <span className="task-group-count">
                  {selectable.length
                    ? `${activeCount}/${selectable.length}`
                    : `${items.length} 项锁定`}
                </span>
              </div>
              <div className="task-grid">
                {items.map((item) => {
                  let checked = selected.has(item.id);
                  if (item.field === "auto_claim") checked = autoClaim;
                  if (item.field === "search_enabled") checked = searchEnabled;
                  return (
                    <TaskRow
                      item={item}
                      key={item.id}
                      checked={checked}
                      supportLabel={labels[item.support] || item.support}
                      onToggle={onToggle}
                    />
                  );
                })}
              </div>
            </section>
          );
        })}
      </div>

      {chosenCount === 0 ? (
        <p className="task-empty-warning">
          未选择任何卡片任务，基础模式只会执行上方勾选的动作，例如领取已完成奖励。
        </p>
      ) : null}
      <p className="task-picker-note">
        界面列出全部已知类型；带有「仅进阶 AI」或「需人工处理」的行需要更复杂的判断，
        不能由基础规则安全完成，因此保持锁定。
      </p>
    </div>
  );
}
