import {
  ArrowUpRight,
  CheckCircle2,
  Coins,
  HandCoins,
  Search,
  Sparkles,
  TrendingUp,
} from "lucide-react";

const number = new Intl.NumberFormat("zh-CN");

function rangeText(range, suffix = "") {
  if (!range) return `0${suffix}`;
  if (range.high <= 0) return `0${suffix}`;
  if (range.low <= 0) return `最多 ${number.format(range.high)}${suffix}`;
  return `${number.format(range.low)}–${number.format(range.high)}${suffix}`;
}

export default function PointsForecast({ forecast, mode = "basic", onImprove }) {
  if (!forecast || !forecast.daily || !forecast.weekly) return null;

  const daily = forecast.daily;
  const weekly = forecast.weekly;
  const missingCount = Number(forecast.missing_count) || 0;
  const claimOff = forecast.auto_claim === false;
  const hasRoom = missingCount > 0 || claimOff;
  const advanced = mode === "advanced";
  const labels = (forecast.missing_labels || []).slice(0, 3);
  const labelText = labels.length
    ? `${labels.join("、")}${missingCount > labels.length ? ` 等 ${missingCount} 项` : ""}`
    : "";

  return (
    <section className={`points-forecast ${hasRoom ? "has-room" : "is-full"}`}>
      <div className="forecast-aurora" aria-hidden="true" />

      <div className="forecast-main">
        <div className="forecast-eyebrow">
          <span className="forecast-pulse" />
          <span>{advanced ? "进阶 AI · 基础清单估值" : "当前模式 · 本地估算"}</span>
          <span className="forecast-tag">非账户余额</span>
        </div>

        <div className="forecast-numbers">
          <div className="forecast-primary">
            <span className="forecast-plus">+</span>
            <strong className="forecast-daily">{number.format(daily.mid)}</strong>
            <span className="forecast-unit">
              分 <i>/</i> 天
            </span>
          </div>
          <div className="forecast-weekly">
            <span>每周预计</span>
            <strong>+{number.format(weekly.mid)}</strong>
            <span>分</span>
          </div>
        </div>

        <p className="forecast-caption">
          按已勾选的 {forecast.selected_count}/{forecast.selectable_count} 项任务估算，
          每日区间 {rangeText(daily)}，每周区间 {rangeText(weekly)}。
          数据完全留在本机，实际积分以 Rewards 页面为准。
        </p>

        <div className="forecast-chips">
          <span className="forecast-chip is-mint">
            <CheckCircle2 size={11} />
            已选 {forecast.selected_count}/{forecast.selectable_count}
          </span>
          <span className={`forecast-chip ${forecast.search_enabled ? "is-sky" : ""}`}>
            <Search size={11} />
            {forecast.search_enabled
              ? `搜索开启${forecast.search_count ? ` · ${forecast.search_count} 次` : ""}`
              : "搜索未开启"}
          </span>
          <span className={`forecast-chip ${claimOff ? "is-amber" : "is-violet"}`}>
            <HandCoins size={11} />
            自动领取{claimOff ? "关闭" : "开启"}
          </span>
          {advanced ? (
            <span className="forecast-chip is-violet">
              <Sparkles size={11} />
              AI 可额外尝试 {forecast.locked_ai_count} 类
            </span>
          ) : null}
        </div>
      </div>

      {hasRoom ? (
        <button
          type="button"
          className="forecast-gain"
          onClick={() => onImprove?.(forecast)}
          title="跳转到设置里尚未勾选的任务选项"
        >
          <span className="gain-head">
            <span className="gain-kicker">
              <TrendingUp size={13} />
              还有提升空间
            </span>
            <span className="gain-arrow">
              <ArrowUpRight size={15} />
            </span>
          </span>

          {missingCount > 0 ? (
            <>
              <span className="gain-line">
                <strong>{missingCount}</strong>
                <span>项任务尚未启用</span>
              </span>
              <span className="gain-copy">
                {labelText}。全部开启后预计每天再多{" "}
                <b>{rangeText(forecast.missing_daily, " 分")}</b>，每周再多{" "}
                <b>{rangeText(forecast.missing_weekly, " 分")}</b>。
              </span>
            </>
          ) : (
            <>
              <span className="gain-line">
                <strong>1</strong>
                <span>项动作尚未开启</span>
              </span>
              <span className="gain-copy">
                自动领取已关闭，已完成的奖励可能停留在待领取状态。开启后程序只点「领取」，绝不兑换。
              </span>
            </>
          )}

          {missingCount > 0 && claimOff ? (
            <span className="gain-extra">
              <HandCoins size={11} />
              自动领取也处于关闭状态
            </span>
          ) : null}

          <span className="forecast-cta">
            <Coins size={13} />
            一键查看未勾选项
            <ArrowUpRight size={13} />
          </span>
        </button>
      ) : (
        <div className="forecast-gain is-complete">
          <span className="gain-head">
            <span className="gain-kicker">
              <CheckCircle2 size={13} />
              没有提升空间
            </span>
            <span className="gain-arrow is-check">
              <CheckCircle2 size={15} />
            </span>
          </span>
          <span className="gain-line">
            <strong>{forecast.selectable_count}</strong>
            <span>项已全部启用</span>
          </span>
          <span className="gain-copy">
            可勾选的任务类型与搜索动作都已取到当前清单上限。进阶 AI 仍可能处理部分锁定任务。
          </span>
          <span className="forecast-cta is-quiet">全部任务均已勾选</span>
        </div>
      )}
    </section>
  );
}
