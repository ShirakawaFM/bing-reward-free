import { Bot, CircleDot, Sparkles, Zap } from "lucide-react";

export default function Orbit({ running, schedulerRunning, mode }) {
  return (
    <div className="orbit" aria-hidden="true">
      <div className="orbit-aurora" />
      <div className="orbit-ring ring-a">
        <span className="orbit-node node-mint" />
      </div>
      <div className="orbit-ring ring-b">
        <span className="orbit-node node-violet" />
      </div>
      <div className="orbit-ring ring-c">
        <span className="orbit-node node-amber" />
      </div>

      <div className={`orbit-core ${running ? "is-running" : ""}`}>
        <div className="core-sheen" />
        <Sparkles size={36} strokeWidth={1.7} />
        <span>{mode === "advanced" ? "AI PILOT" : "PILOT"}</span>
      </div>

      <div className="orbit-chip chip-scan">
        <CircleDot size={13} />
        任务扫描
      </div>
      <div className="orbit-chip chip-claim">
        <Zap size={13} />
        自动领取
      </div>
      <div className="orbit-chip chip-ai">
        <Bot size={13} />
        {mode === "advanced" ? "DeepSeek" : "规则引擎"}
      </div>

      <div className="orbit-caption">
        <span className={`orbit-live ${running ? "is-on" : ""}`} />
        {running ? "正在巡航" : schedulerRunning ? "等待下一班" : "待命中"}
      </div>
    </div>
  );
}
