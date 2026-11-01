import { Loader2, RefreshCw, Zap } from "lucide-react";

export default function BootScreen({ connection, onRetry }) {
  const failed = connection === "offline" || connection === "unauthorized";

  return (
    <div className="boot-screen">
      <div className="boot-glow" />
      <div className="boot-mark">
        <Zap size={26} strokeWidth={2.4} />
        <span className="boot-ring" />
      </div>
      <h1>
        Rewards <em>Pilot</em>
      </h1>
      {failed ? (
        <>
          <p className="boot-status is-error">
            {connection === "unauthorized"
              ? "界面令牌已失效，请关闭窗口并从应用重新打开。"
              : "无法连接本地服务，请确认程序仍在运行。"}
          </p>
          <button type="button" className="btn btn-ghost" onClick={onRetry}>
            <RefreshCw size={16} />
            重新连接
          </button>
        </>
      ) : (
        <p className="boot-status">
          <Loader2 size={15} className="spin" />
          正在唤醒本地控制台…
        </p>
      )}
      <span className="boot-foot">LOCAL · PLAYWRIGHT · EDGE</span>
    </div>
  );
}
