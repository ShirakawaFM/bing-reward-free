import { useCallback, useEffect, useRef, useState } from "react";
import { AnimatePresence, motion } from "framer-motion";
import { PowerOff, WifiOff, Zap } from "lucide-react";
import Ambient from "./components/Ambient";
import BootScreen from "./components/BootScreen";
import LoginModal from "./components/LoginModal";
import OnboardingWizard from "./components/OnboardingWizard";
import Sidebar from "./components/Sidebar";
import Toasts from "./components/Toasts";
import TopBar from "./components/TopBar";
import Overview from "./views/Overview";
import Logs from "./views/Logs";
import Gallery from "./views/Gallery";
import Settings from "./views/Settings";
import { useAppData } from "./hooks/useAppData";
import { useToasts } from "./hooks/useToasts";
import { api, APP_VERSION } from "./lib/api";

export default function App() {
  const {
    state,
    connection,
    logs,
    screenshots,
    shotsLoading,
    refreshState,
    refreshScreenshots,
    clearLogs,
  } = useAppData();
  const { toasts, push, dismiss } = useToasts();

  const [view, setView] = useState("overview");
  const [settingsFocus, setSettingsFocus] = useState(null);
  const [mode, setMode] = useState("basic");
  const [loginOpen, setLoginOpen] = useState(false);
  const [busy, setBusy] = useState({ run: false, login: false, scheduler: false });
  const [refreshing, setRefreshing] = useState(false);
  const [shutdown, setShutdown] = useState(false);
  const [onboardingOpen, setOnboardingOpen] = useState(false);

  const modeTouched = useRef(false);
  const prevFinish = useRef(undefined);
  const prevLogin = useRef(null);
  const loginCloseTimer = useRef(null);
  const onboardingPrompted = useRef(false);

  useEffect(() => {
    if (!state?.onboarding) return;
    if (!state.onboarding.seen && !onboardingPrompted.current) {
      onboardingPrompted.current = true;
      setOnboardingOpen(true);
    }
  }, [state?.onboarding?.seen]);

  useEffect(() => {
    if (!modeTouched.current && state?.summary?.mode) {
      setMode(state.summary.mode);
    }
  }, [state?.summary?.mode]);

  useEffect(() => {
    if (!state) return;
    const finish = state.job?.finished_at;
    if (prevFinish.current === undefined) {
      prevFinish.current = finish || null;
      return;
    }
    if (finish && finish !== prevFinish.current) {
      prevFinish.current = finish;
      const ok = state.job?.state === "success";
      push({
        tone: ok ? "success" : "error",
        title: ok ? "任务完成" : "任务结束，有待确认项",
        message: state.job?.message || "详情请查看实时日志。",
        duration: 5200,
      });
      refreshScreenshots();
    }
  }, [state, push, refreshScreenshots]);

  useEffect(() => {
    const current = state?.login?.state;
    if (!current) return;
    if (prevLogin.current === null) {
      prevLogin.current = current;
      return;
    }
    if (current !== prevLogin.current) {
      prevLogin.current = current;
      if (current === "success") {
        push({
          tone: "success",
          title: "登录成功",
          message: "登录态已保存，现在可以运行任务了。",
        });
        refreshScreenshots();
        if (loginCloseTimer.current) window.clearTimeout(loginCloseTimer.current);
        loginCloseTimer.current = window.setTimeout(() => {
          setLoginOpen(false);
        }, 1600);
      } else if (current === "error") {
        push({
          tone: "error",
          title: "登录未完成",
          message: state.login?.message || "请重新打开登录窗口。",
        });
      }
    }
  }, [state, push, refreshScreenshots]);

  useEffect(
    () => () => {
      if (loginCloseTimer.current) window.clearTimeout(loginCloseTimer.current);
    },
    [],
  );

  const setBusyKey = (key, value) =>
    setBusy((current) => ({ ...current, [key]: value }));

  const navigate = useCallback((next, options = {}) => {
    setView(next);
    setSettingsFocus(
      next === "settings" && options.focus
        ? { focus: options.focus, token: Date.now(), ids: options.ids || [] }
        : null,
    );
  }, []);

  const runJob = useCallback(
    async (overrideMode) => {
      const target = typeof overrideMode === "string" ? overrideMode : mode;
      setBusyKey("run", true);
      try {
        await api.run(target);
        push({
          tone: "success",
          title: "任务已启动",
          message:
            target === "advanced"
              ? "进阶 AI 模式启动，浏览器会自动打开，决策轨迹见实时日志。"
              : "基础模式启动，正在扫描 Rewards 任务页。",
        });
        await refreshState();
      } catch (error) {
        push({ tone: "error", title: "无法启动任务", message: error.message });
      } finally {
        setBusyKey("run", false);
      }
    },
    [mode, push, refreshState],
  );

  const changeMode = (next) => {
    modeTouched.current = true;
    setMode(next);
  };

  const loginStart = async () => {
    setBusyKey("login", true);
    try {
      await api.loginStart();
      push({
        tone: "info",
        title: "登录窗口已打开",
        message: "请在弹出的 Edge 窗口中完成 Microsoft 登录。",
      });
      await refreshState();
    } catch (error) {
      push({ tone: "error", title: "无法打开登录窗口", message: error.message });
    } finally {
      setBusyKey("login", false);
    }
  };

  const loginFinish = async () => {
    setBusyKey("login", true);
    try {
      await api.loginFinish();
      await refreshState();
    } catch (error) {
      push({ tone: "error", title: "检查登录失败", message: error.message });
    } finally {
      setBusyKey("login", false);
    }
  };

  const loginCancel = async () => {
    setBusyKey("login", true);
    try {
      await api.loginCancel();
      await refreshState();
    } catch (error) {
      push({ tone: "error", title: "取消登录失败", message: error.message });
    } finally {
      setBusyKey("login", false);
    }
  };

  const openLogin = () => {
    setLoginOpen(true);
  };

  const toggleScheduler = async (next) => {
    setBusyKey("scheduler", true);
    try {
      if (next) await api.schedulerStart();
      else await api.schedulerStop();
      push({
        tone: next ? "success" : "info",
        title: next ? "每日调度已开启" : "每日调度已暂停",
        message: next
          ? "程序会保持待命，到点自动执行任务。"
          : "自动巡航已停止，仍可手动运行。",
      });
      await refreshState();
    } catch (error) {
      push({ tone: "error", title: "调度操作失败", message: error.message });
    } finally {
      setBusyKey("scheduler", false);
    }
  };

  const refreshAll = async () => {
    setRefreshing(true);
    try {
      await Promise.all([refreshState(), refreshScreenshots()]);
      push({ tone: "info", title: "状态已刷新", message: "已获取最新运行状态与截图。" });
    } catch (error) {
      push({ tone: "error", title: "刷新失败", message: error.message });
    } finally {
      setRefreshing(false);
    }
  };

  const handleShutdown = useCallback(async () => {
    await api.shutdown();
    setShutdown(true);
  }, []);

  const handleOnboardingDone = useCallback(
    (action, meta = {}) => {
      setOnboardingOpen(false);
      refreshState().catch(() => {});
      if (action === "completed") {
        const applied = [];
        if (meta.mode) {
          applied.push(meta.mode === "advanced" ? "进阶 AI" : "基础模式");
        }
        if (Number.isFinite(meta.taskCount)) {
          applied.push(`${meta.taskCount} 类任务`);
        }
        if (meta.scheduleChanged) {
          applied.push(`每天 ${meta.runAt || "--:--"}`);
        }
        if (meta.schedulerChanged) {
          applied.push(meta.schedulerEnabled ? "每日调度已开启" : "调度已关闭");
        }
        push({
          tone: "success",
          title: meta.saved ? "初始化完成，设置已保存" : "初始化完成",
          message: meta.saved
            ? applied.length
              ? `已应用：${applied.join(" · ")}。可随时在设置中调整。`
              : "向导中的选项已写入本机配置。"
            : meta.schedulerChanged
              ? applied.length
                ? `已应用：${applied[applied.length - 1]}。`
                : "调度状态已更新。"
              : "没有需要保存的改动，现有设置保持不变。",
          duration: 4600,
        });
      } else if (action === "skipped") {
        push({
          tone: "info",
          title: "初始化教程已跳过",
          message: "现有配置保持不变，可随时在设置里重新打开教程。",
          duration: 4200,
        });
      }
    },
    [push, refreshState],
  );

  const handleClearLogs = () => {
    clearLogs();
    push({
      tone: "info",
      title: "界面日志已清空",
      message: "完整日志仍保存在 logs/rewards_bot.log。",
    });
  };

  const retryConnect = async () => {
    try {
      await refreshState();
    } catch {
      // 轮询会持续重试。
    }
  };

  if (!state) {
    return <BootScreen connection={connection} onRetry={retryConnect} />;
  }

  const pageTransition = {
    initial: { opacity: 0, y: 14 },
    animate: { opacity: 1, y: 0 },
    exit: { opacity: 0, y: -8 },
    transition: { duration: 0.3, ease: [0.22, 1, 0.36, 1] },
  };

  const eco = Boolean(state?.power?.enabled);

  return (
    <div className={`app-shell ${eco ? "is-eco" : ""}`}>
      <Ambient />
      <Sidebar
        view={view}
        onNavigate={navigate}
        scheduler={state.scheduler || {}}
        connection={connection}
        version={state.version || APP_VERSION}
        loginActive={Boolean(state.login?.active)}
      />

      <div className="workspace">
        <TopBar
          view={view}
          scheduler={state.scheduler || {}}
          job={state.job || {}}
          loginActive={Boolean(state.login?.active)}
          connection={connection}
          power={state.power || {}}
          onRefresh={refreshAll}
          refreshing={refreshing}
        />

        {connection !== "online" ? (
          <div className={`connection-banner ${connection === "unauthorized" ? "is-auth" : ""}`}>
            <WifiOff size={15} />
            <span>
              {connection === "unauthorized"
                ? "界面令牌已失效。请关闭这个窗口并从应用重新打开。"
                : "本地服务连接中断，正在后台自动重试。已运行的任务可能仍在继续。"}
            </span>
            {connection === "unauthorized" ? (
              <button type="button" onClick={() => window.location.reload()}>
                重新加载
              </button>
            ) : (
              <button type="button" onClick={retryConnect}>
                立即重试
              </button>
            )}
          </div>
        ) : null}

        <main className="main">
          <AnimatePresence mode="wait" initial={false}>
            <motion.div key={view} {...pageTransition} className="page-motion">
              {view === "overview" ? (
                <Overview
                  state={state}
                  logs={logs}
                  screenshots={screenshots}
                  mode={mode}
                  onModeChange={changeMode}
                  onRun={runJob}
                  onLogin={openLogin}
                  onToggleScheduler={toggleScheduler}
                  onNavigate={navigate}
                  busy={busy}
                  power={state.power || {}}
                />
              ) : null}
              {view === "logs" ? (
                <Logs
                  logs={logs}
                  onClear={handleClearLogs}
                  onToast={push}
                />
              ) : null}
              {view === "gallery" ? (
                <Gallery
                  screenshots={screenshots}
                  loading={shotsLoading}
                  onRefresh={refreshScreenshots}
                />
              ) : null}
              {view === "settings" ? (
                <Settings
                  state={state}
                  focusRequest={settingsFocus}
                  onSaved={() => {
                    refreshState();
                    refreshScreenshots();
                  }}
                  onPowerChanged={() => {
                    refreshState();
                  }}
                  onToast={push}
                  onShutdown={handleShutdown}
                  onShowOnboarding={() => setOnboardingOpen(true)}
                />
              ) : null}
            </motion.div>
          </AnimatePresence>
        </main>

        <footer className="app-footer">
          <span className="footer-left">
            <span className="footer-dot" />
            Rewards Pilot 本地控制台
          </span>
          <span>仅用于个人账号 · 请遵守 Microsoft Rewards 使用条款</span>
        </footer>
      </div>

      <LoginModal
        open={loginOpen}
        onClose={() => setLoginOpen(false)}
        login={state.login || {}}
        jobRunning={Boolean(state.job?.running)}
        busy={busy.login}
        onStart={loginStart}
        onFinish={loginFinish}
        onCancel={loginCancel}
      />

      <OnboardingWizard
        open={onboardingOpen}
        state={state}
        loginOpen={loginOpen}
        onOpenLogin={openLogin}
        onDone={handleOnboardingDone}
        onToast={push}
      />

      <Toasts items={toasts} onDismiss={dismiss} />

      <AnimatePresence>
        {shutdown ? (
          <motion.div
            className="shutdown-screen"
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
          >
            <div className="shutdown-card">
              <div className="shutdown-mark">
                <Zap size={26} />
              </div>
              <span className="shutdown-kicker">LOCAL SERVICE OFFLINE</span>
              <h1>Rewards Pilot 已退出</h1>
              <p>每日调度与本地控制台均已停止，可以关闭这个窗口了。</p>
              <div className="shutdown-meta">
                <PowerOff size={14} />
                登录态与配置已保留在本机
              </div>
            </div>
          </motion.div>
        ) : null}
      </AnimatePresence>
    </div>
  );
}
