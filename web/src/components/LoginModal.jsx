import {
  AlertTriangle,
  CheckCircle2,
  ExternalLink,
  Fingerprint,
  LogIn,
  ShieldCheck,
  UserRound,
} from "lucide-react";
import { Modal, Spinner } from "./ui";

const STATUS = {
  idle: {
    title: "连接你的 Microsoft 账号",
    text: "首次使用需要在一个独立的 Edge 窗口完成 Microsoft 登录。登录态只保存在本机，不会上传。",
    tone: "idle",
    icon: UserRound,
  },
  opening: {
    title: "正在打开登录窗口",
    text: "Edge 正在启动，请稍候…",
    tone: "waiting",
    icon: LogIn,
  },
  waiting: {
    title: "请在 Edge 窗口完成登录",
    text: "登录、验证码或双重验证完成后，回到这里点击「我已完成登录」。",
    tone: "waiting",
    icon: Fingerprint,
  },
  checking: {
    title: "正在检查登录状态",
    text: "正在重新打开 Rewards 仪表盘，确认登录态是否完整…",
    tone: "waiting",
    icon: Spinner,
  },
  canceling: {
    title: "正在关闭登录窗口",
    text: "浏览器窗口即将关闭。",
    tone: "waiting",
    icon: Spinner,
  },
  success: {
    title: "登录态已保存",
    text: "可以关闭此窗口，直接开始运行任务了。",
    tone: "success",
    icon: CheckCircle2,
  },
  error: {
    title: "登录没有完成",
    text: "请检查上面的提示，然后重新打开登录窗口。",
    tone: "error",
    icon: AlertTriangle,
  },
  canceled: {
    title: "已取消登录",
    text: "随时可以重新打开登录窗口。",
    tone: "idle",
    icon: UserRound,
  },
};

export default function LoginModal({
  open,
  onClose,
  login,
  jobRunning,
  busy,
  onStart,
  onFinish,
  onCancel,
}) {
  const state = login?.state || "idle";
  const active = Boolean(login?.active);
  const meta = STATUS[state] || STATUS.idle;
  const Icon = meta.icon;
  const waiting = active && ["opening", "waiting"].includes(state);
  const checking = ["checking", "canceling", "opening"].includes(state);
  const canFinish = state === "waiting" && !busy;
  const canCancel = active && !checking && !busy;
  const canStart = !active && !jobRunning && !busy && !checking;

  return (
    <Modal open={open} onClose={onClose} labelledBy="login-title" className="login-modal">
      <div className={`login-hero tone-${meta.tone}`}>
        <div className="login-visual">
          <span className="login-halo" />
          <span className="login-icon">
            {state === "checking" || state === "canceling" ? (
              <Spinner size={26} />
            ) : (
              <Icon size={30} />
            )}
          </span>
          {waiting ? <span className="login-pulse" /> : null}
        </div>
        <span className="login-kicker">MICROSOFT REWARDS</span>
        <h2 id="login-title">{meta.title}</h2>
        <p>{state === "error" && login?.message ? login.message : meta.text}</p>
        {state === "waiting" && login?.message ? (
          <p className="login-submessage">{login.message}</p>
        ) : null}
      </div>

      <div className="login-steps">
        <div className={`login-step ${active ? "is-done" : ""}`}>
          <span>01</span>
          <div>
            <strong>打开独立登录窗口</strong>
            <small>使用系统 Edge，不影响你日常浏览</small>
          </div>
        </div>
        <div className={`login-step ${state === "waiting" ? "is-current" : active ? "is-done" : ""}`}>
          <span>02</span>
          <div>
            <strong>完成 Microsoft 登录</strong>
            <small>密码与验证码只由微软页面接收</small>
          </div>
        </div>
        <div className={`login-step ${state === "success" ? "is-done" : ""}`}>
          <span>03</span>
          <div>
            <strong>保存本地登录态</strong>
            <small>写入 .browser-profile，下次直接复用</small>
          </div>
        </div>
      </div>

      {jobRunning ? (
        <div className="login-note">
          <AlertTriangle size={15} />
          任务正在运行，请等待当前任务结束后再登录。
        </div>
      ) : null}

      <div className="login-actions">
        {canFinish ? (
          <button type="button" className="btn btn-primary" onClick={onFinish}>
            <CheckCircle2 size={17} />
            我已完成登录
          </button>
        ) : null}
        {canStart ? (
          <button type="button" className="btn btn-primary" onClick={onStart}>
            <LogIn size={17} />
            {["error", "canceled"].includes(state) ? "重新打开登录窗口" : "打开登录窗口"}
          </button>
        ) : null}
        {state === "success" ? (
          <button type="button" className="btn btn-primary" onClick={onClose}>
            <CheckCircle2 size={17} />
            开始使用
          </button>
        ) : null}
        {canCancel ? (
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            取消登录
          </button>
        ) : null}
        {!active && !busy && state !== "success" ? (
          <button type="button" className="btn btn-quiet" onClick={onClose}>
            稍后再说
          </button>
        ) : null}
        {checking && !busy ? (
          <button type="button" className="btn btn-ghost" onClick={onClose}>
            后台继续
          </button>
        ) : null}
      </div>

      <div className="login-privacy">
        <ShieldCheck size={14} />
        <span>
          程序不会读取或保存你的密码，登录过程完全发生在微软官方页面。
        </span>
        <a
          href="https://rewards.bing.com/dashboard"
          target="_blank"
          rel="noreferrer"
          className="login-link"
        >
          Rewards 仪表盘
          <ExternalLink size={12} />
        </a>
      </div>
    </Modal>
  );
}
