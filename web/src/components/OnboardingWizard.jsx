import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import {
  AlertTriangle,
  ArrowLeft,
  ArrowRight,
  CalendarClock,
  Check,
  CheckCircle2,
  Eye,
  EyeOff,
  KeyRound,
  Leaf,
  ListChecks,
  Loader2,
  Lock,
  LogIn,
  MousePointerClick,
  Rocket,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  UserRound,
  X,
  Zap,
} from "lucide-react";
import { Switch } from "./ui";
import { api } from "../lib/api";
import { withCurrentTimezone } from "../lib/timezones";

const STEPS = [
  {
    id: "account",
    label: "登录",
    hint: "微软账号 · 可选",
    icon: UserRound,
  },
  {
    id: "mode",
    label: "模式",
    hint: "基础或进阶 AI",
    icon: SlidersHorizontal,
  },
  {
    id: "tasks",
    label: "任务",
    hint: "勾选卡片类型",
    icon: ListChecks,
  },
  {
    id: "schedule",
    label: "运行",
    hint: "时间与调度",
    icon: CalendarClock,
  },
];

function draftFrom(settings, schedulerRunning) {
  return {
    mode: settings.general.mode,
    runAt: settings.general.run_at,
    timezone: settings.general.timezone,
    taskTypes: [...(settings.basic.task_types || [])],
    autoClaim: Boolean(settings.basic.auto_claim),
    schedulerEnabled: Boolean(schedulerRunning),
  };
}

function StepHead({ icon: Icon, tone = "mint", kicker, title, description }) {
  return (
    <header className="onboarding-step-head">
      <span className={`onboarding-step-icon is-${tone}`}>
        <Icon size={22} />
      </span>
      <div className="onboarding-step-head-copy">
        <span className="onboarding-kicker">{kicker}</span>
        <h2 id="onboarding-title">{title}</h2>
        {description ? <p>{description}</p> : null}
      </div>
      <span className="onboarding-optional">可跳过</span>
    </header>
  );
}

export default function OnboardingWizard({
  open,
  state,
  loginOpen = false,
  onOpenLogin,
  onDone,
  onToast,
}) {
  const [step, setStep] = useState(0);
  const [direction, setDirection] = useState(1);
  const [loading, setLoading] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [settings, setSettings] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [form, setForm] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [saving, setSaving] = useState(false);
  const [saveError, setSaveError] = useState("");

  const dialogRef = useRef(null);
  const scrollRef = useRef(null);
  const loadSeq = useRef(0);
  const stateRef = useRef(state);
  stateRef.current = state;

  const loadSettings = useCallback(async () => {
    const seq = loadSeq.current + 1;
    loadSeq.current = seq;
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.settings();
      if (seq !== loadSeq.current) return false;
      const next = draftFrom(
        data.settings,
        stateRef.current?.scheduler?.running,
      );
      setSettings(data.settings);
      setCatalog(data.task_catalog || null);
      setForm(next);
      setBaseline(next);
      return true;
    } catch (error) {
      if (seq !== loadSeq.current) return false;
      setLoadError(error.message || "无法读取当前配置。");
      return false;
    } finally {
      if (seq === loadSeq.current) setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (!open) {
      loadSeq.current += 1;
      return undefined;
    }
    loadSeq.current += 1;
    setStep(0);
    setDirection(1);
    setLoading(false);
    setLoadError("");
    setSaveError("");
    setSaving(false);
    setApiKey("");
    setShowKey(false);
    setSettings(null);
    setCatalog(null);
    setForm(null);
    setBaseline(null);
    loadSettings();
    return () => {
      loadSeq.current += 1;
    };
  }, [open, loadSettings]);

  useEffect(() => {
    if (!open) return undefined;
    document.body.classList.add("wizard-open");
    const previous = document.activeElement;
    const timer = window.setTimeout(() => dialogRef.current?.focus(), 80);
    return () => {
      document.body.classList.remove("wizard-open");
      window.clearTimeout(timer);
      if (previous && typeof previous.focus === "function") previous.focus();
    };
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const node = scrollRef.current;
    if (node) node.scrollTop = 0;
  }, [step, open]);

  const markSeen = useCallback(
    async (action, meta) => {
      try {
        await api.completeOnboarding(action);
      } catch (error) {
        onToast?.({
          tone: "error",
          title: "教程状态未保存",
          message: `${error.message} 下次启动时可能再次显示教程。`,
        });
      }
      onDone?.(action, meta);
    },
    [onDone, onToast],
  );

  const skip = useCallback(async () => {
    if (saving) return;
    setSaving(true);
    setSaveError("");
    try {
      await markSeen("skipped", { saved: false });
    } finally {
      setSaving(false);
    }
  }, [markSeen, saving]);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key !== "Escape") return;
      if (loginOpen || saving) return;
      skip();
    };
    document.addEventListener("keydown", onKeyDown);
    return () => document.removeEventListener("keydown", onKeyDown);
  }, [open, loginOpen, saving, skip]);

  const update = (key, value) => {
    setForm((current) => (current ? { ...current, [key]: value } : current));
  };

  const toggleTask = (taskId) => {
    setForm((current) => {
      if (!current) return current;
      const selected = new Set(current.taskTypes);
      if (selected.has(taskId)) selected.delete(taskId);
      else selected.add(taskId);
      const ordered = (catalog?.basic_card_task_ids || []).filter((id) =>
        selected.has(id),
      );
      return { ...current, taskTypes: ordered };
    });
  };

  const keyAvailable = Boolean(
    settings?.advanced?.api_key_set || apiKey.trim(),
  );
  const advancedBlocked = form?.mode === "advanced" && !keyAvailable;
  const runAtValid = /^([01]?\d|2[0-3]):[0-5]\d$/.test(form?.runAt || "");
  const scheduleValid = runAtValid && Boolean(form?.timezone);

  const taskGroups = useMemo(() => {
    if (!catalog) return [];
    return catalog.groups
      .filter((group) => group.id !== "special")
      .map((group) => ({
        ...group,
        items: catalog.items.filter(
          (item) =>
            item.group === group.id &&
            item.support === "basic" &&
            !item.field,
        ),
      }))
      .filter((group) => group.items.length);
  }, [catalog]);

  const lockedAiCount =
    catalog?.items.filter((item) => item.support === "ai").length || 0;
  const lockedManualCount =
    catalog?.items.filter((item) => item.support === "manual").length || 0;
  const timezoneOptions = useMemo(
    () => withCurrentTimezone(form?.timezone),
    [form?.timezone],
  );

  const login = state?.login || {};
  const loginActive = Boolean(login.active);
  const loginSuccess = login.state === "success";
  const jobRunning = Boolean(state?.job?.running);
  const firstRun = Boolean(state?.onboarding?.show);

  const applySettings = async () => {
    const payload = {};
    const general = {};
    const canSwitchMode = form.mode !== "advanced" || keyAvailable;
    if (form.mode !== baseline.mode && canSwitchMode) {
      general.mode = form.mode;
    }
    if (form.runAt !== baseline.runAt) general.run_at = form.runAt;
    if (form.timezone !== baseline.timezone) {
      general.timezone = form.timezone;
    }
    if (Object.keys(general).length) payload.general = general;

    const basic = {};
    if (form.taskTypes.join(",") !== baseline.taskTypes.join(",")) {
      basic.task_types = [...form.taskTypes];
    }
    if (form.autoClaim !== baseline.autoClaim) {
      basic.auto_claim = form.autoClaim;
    }
    if (Object.keys(basic).length) payload.basic = basic;

    if (apiKey.trim() && form.mode === "advanced") {
      payload.advanced = { api_key: apiKey.trim() };
    }
    if (!Object.keys(payload).length) return false;

    const data = await api.saveSettings(payload);
    setSettings(data.settings);
    if (data.task_catalog) setCatalog(data.task_catalog);
    setApiKey("");
    setShowKey(false);
    return true;
  };

  const applyScheduler = async () => {
    if (form.schedulerEnabled === baseline.schedulerEnabled) return;
    try {
      if (form.schedulerEnabled) {
        await api.schedulerStart(false);
      } else {
        await api.schedulerStop();
      }
    } catch (error) {
      if (error.status !== 409) throw error;
    }
  };

  const finish = async () => {
    if (saving) return;
    if (!form) return;
    if (advancedBlocked) {
      setSaveError("进阶 AI 需要 DeepSeek API Key：填写 Key，或切回基础模式。");
      return;
    }
    if (!scheduleValid) {
      setSaveError("请填写有效的运行时间和时区。");
      return;
    }
    setSaving(true);
    setSaveError("");
    let settingsSaved = false;
    const schedulerChanged =
      form.schedulerEnabled !== baseline.schedulerEnabled;
    const scheduleChanged =
      form.runAt !== baseline.runAt || form.timezone !== baseline.timezone;
    try {
      settingsSaved = await applySettings();
      await applyScheduler();
      await markSeen("completed", {
        saved: settingsSaved,
        schedulerChanged,
        schedulerEnabled: form.schedulerEnabled,
        scheduleChanged,
        taskCount: form.taskTypes.length,
        mode: form.mode,
        runAt: form.runAt,
      });
    } catch (error) {
      setSaveError(
        settingsSaved
          ? `设置已保存，但调度操作失败：${error.message}`
          : error.message || "保存设置失败，请重试。",
      );
    } finally {
      setSaving(false);
    }
  };

  const goNext = () => {
    if (step >= STEPS.length - 1) {
      finish();
      return;
    }
    setDirection(1);
    setStep((current) => Math.min(STEPS.length - 1, current + 1));
  };

  const goBack = () => {
    setDirection(-1);
    setStep((current) => Math.max(0, current - 1));
  };

  const renderAccount = () => {
    const stateTone = loginActive
      ? "waiting"
      : loginSuccess
        ? "success"
        : "idle";
    const statusTitle = loginActive
      ? login.state === "checking"
        ? "正在检查登录状态"
        : "登录窗口已打开"
      : loginSuccess
        ? "本次会话已确认登录"
        : "尚未在本会话验证登录";
    const statusText = loginActive
      ? login.message || "请在弹出的 Edge 窗口完成 Microsoft 登录。"
      : loginSuccess
        ? "登录态已保存在本机 .browser-profile，下一次可以直接复用。"
        : "如果账号已经登录过，也可以直接点“下一步”。";
    return (
      <div className="onboarding-step">
        <StepHead
          icon={UserRound}
          tone="sky"
          kicker="STEP 01 · ACCOUNT"
          title="先登录，或稍后再说。"
          description="登录在微软官方页面完成；密码不会经过本程序。"
        />
        <div className={`onboarding-login-card is-${stateTone}`}>
          <span className="onboarding-login-icon">
            {loginActive ? (
              <Loader2 size={24} className="spin" />
            ) : loginSuccess ? (
              <CheckCircle2 size={24} />
            ) : (
              <UserRound size={24} />
            )}
          </span>
          <div>
            <strong>{statusTitle}</strong>
            <p>{statusText}</p>
          </div>
          <span className="onboarding-login-badge">
            {loginActive ? "进行中" : loginSuccess ? "已确认" : "可选"}
          </span>
        </div>
        <div className="onboarding-login-actions">
          <button
            type="button"
            className="btn btn-primary onboarding-v2-cta"
            onClick={onOpenLogin}
            disabled={jobRunning || saving}
          >
            {loginActive ? (
              <Loader2 size={17} className="spin" />
            ) : (
              <LogIn size={17} />
            )}
            {loginActive
              ? "查看登录进度"
              : loginSuccess
                ? "重新打开登录窗口"
                : "打开 Microsoft 登录"}
          </button>
          <span>只打开登录页，不运行任务或领取积分。</span>
        </div>
        <div className="onboarding-info-strip">
          <ShieldCheck size={15} />
          <span>
            登录态仅写入本机 <code>.browser-profile</code>，不会上传账号或密码。
          </span>
        </div>
        {jobRunning ? (
          <p className="onboarding-inline-warn">
            <AlertTriangle size={14} />
            任务正在运行，结束后才能打开登录窗口。
          </p>
        ) : null}
        {loading ? (
          <p className="onboarding-v2-hintline">
            <Loader2 size={13} className="spin" />
            正在读取本机设置…
          </p>
        ) : null}
        {loadError ? (
          <div className="onboarding-v2-retry">
            <p className="onboarding-inline-warn">
              <AlertTriangle size={14} />
              无法读取本机设置：{loadError}
            </p>
            <button type="button" className="btn btn-quiet" onClick={loadSettings}>
              <Loader2 size={14} />
              重新读取
            </button>
          </div>
        ) : null}
      </div>
    );
  };

  const renderMode = () => (
    <div className="onboarding-step">
      <StepHead
        icon={SlidersHorizontal}
        tone="violet"
        kicker="STEP 02 · MODE"
        title="选一个运行模式。"
        description="基础模式开箱即用；进阶 AI 需要 DeepSeek Key。"
      />
      <div
        className="onboarding-mode-grid"
        role="radiogroup"
        aria-label="默认执行模式"
      >
        <button
          type="button"
          role="radio"
          aria-checked={form.mode === "basic"}
          className={`onboarding-mode ${form.mode === "basic" ? "is-active" : ""}`}
          onClick={() => update("mode", "basic")}
        >
          <span className="onboarding-mode-icon is-mint">
            <ShieldCheck size={21} />
          </span>
          <span className="onboarding-mode-copy">
            <strong>
              基础模式
              <em>推荐</em>
            </strong>
            <p>内置规则，不调用大模型。</p>
          </span>
          <span className="onboarding-mode-check">
            {form.mode === "basic" ? <Check size={13} /> : null}
          </span>
        </button>
        <button
          type="button"
          role="radio"
          aria-checked={form.mode === "advanced"}
          className={`onboarding-mode is-ai ${
            form.mode === "advanced" ? "is-active" : ""
          }`}
          onClick={() => update("mode", "advanced")}
        >
          <span className="onboarding-mode-icon is-violet">
            <Sparkles size={21} />
          </span>
          <span className="onboarding-mode-copy">
            <strong>进阶 AI</strong>
            <p>页面元素交给 DeepSeek 决策。</p>
          </span>
          <span className="onboarding-mode-check">
            {form.mode === "advanced" ? <Check size={13} /> : null}
          </span>
        </button>
      </div>

      {form.mode === "advanced" ? (
        <div className="onboarding-key-card">
          <div className="onboarding-key-head">
            <span className="onboarding-key-icon">
              <KeyRound size={17} />
            </span>
            <div>
              <strong>DeepSeek API Key</strong>
              <p>
                {settings?.advanced?.api_key_set
                  ? "本机已配置；留空即可保持不变。"
                  : "粘贴 Key 后会随最终保存写入本机。"}
              </p>
            </div>
            <span
              className={`onboarding-key-status ${keyAvailable ? "is-ok" : ""}`}
            >
              {apiKey.trim()
                ? "将保存"
                : settings?.advanced?.api_key_set
                  ? "已配置"
                  : "未配置"}
            </span>
          </div>
          <div className="onboarding-key-row">
            <div className="input-wrap">
              <KeyRound size={15} />
              <input
                type={showKey ? "text" : "password"}
                value={apiKey}
                placeholder={
                  settings?.advanced?.api_key_set
                    ? "留空保持不变 · 输入新 Key 可替换"
                    : "sk-..."
                }
                onChange={(event) => setApiKey(event.target.value)}
                autoComplete="off"
                spellCheck="false"
                aria-label="DeepSeek API Key"
              />
              <button
                type="button"
                className="input-eye"
                onClick={() => setShowKey((value) => !value)}
                aria-label={showKey ? "隐藏 Key" : "显示 Key"}
              >
                {showKey ? <EyeOff size={15} /> : <Eye size={15} />}
              </button>
            </div>
          </div>
          <p className="onboarding-key-note">
            Key 只写入本机 config.toml，不进入日志或控制台接口。
          </p>
          {advancedBlocked ? (
            <p className="onboarding-inline-warn">
              <AlertTriangle size={14} />
              缺少 Key：填写后才能继续，或切回基础模式。
            </p>
          ) : null}
        </div>
      ) : (
        <div className="onboarding-info-strip">
          <ShieldCheck size={15} />
          <span>基础模式不会向任何大模型服务发送页面数据。</span>
        </div>
      )}
    </div>
  );

  const renderTasks = () => {
    const selected = new Set(form.taskTypes);
    const total = catalog?.basic_card_task_ids.length || 0;
    return (
      <div className="onboarding-step">
        <StepHead
          icon={ListChecks}
          tone="mint"
          kicker="STEP 03 · TASKS"
          title="挑要自动做的事。"
          description="只处理勾选的卡片，未选的会跳过并写入日志。"
        />
        <div className="onboarding-task-toolbar">
          <span className="onboarding-task-count">
            已选 <strong>{selected.size}</strong> / {total}
          </span>
          <div className="onboarding-task-tools">
            <button
              type="button"
              onClick={() =>
                update("taskTypes", [...(catalog?.default_task_types || [])])
              }
            >
              推荐
            </button>
            <button
              type="button"
              onClick={() =>
                update("taskTypes", [...(catalog?.basic_card_task_ids || [])])
              }
            >
              全选
            </button>
            <button type="button" onClick={() => update("taskTypes", [])}>
              清空
            </button>
          </div>
        </div>

        <div className="onboarding-task-groups">
          {taskGroups.map((group) => (
            <section className="onboarding-task-group" key={group.id}>
              <div className="onboarding-task-group-head">
                <strong>{group.label}</strong>
                <span>{group.items.length} 项</span>
              </div>
              <div className="onboarding-v2-task-grid">
                {group.items.map((item) => {
                  const checked = selected.has(item.id);
                  return (
                    <button
                      type="button"
                      key={item.id}
                      className={`onboarding-v2-task ${
                        checked ? "is-checked" : ""
                      }`}
                      onClick={() => toggleTask(item.id)}
                      aria-pressed={checked}
                      title={item.description}
                    >
                      <span className="task-check">
                        {checked ? (
                          <Check size={12} strokeWidth={3} />
                        ) : (
                          <MousePointerClick size={10} />
                        )}
                      </span>
                      <span>{item.label}</span>
                    </button>
                  );
                })}
              </div>
            </section>
          ))}
        </div>

        <div className="onboarding-action-row">
          <span className="onboarding-action-icon is-mint">
            <CheckCircle2 size={16} />
          </span>
          <div>
            <strong>自动领取已完成奖励</strong>
            <p>只点击“领取 / Claim”，绝不兑换积分的“Redeem”。</p>
          </div>
          <Switch
            checked={Boolean(form.autoClaim)}
            onChange={(value) => update("autoClaim", value)}
            label="自动领取"
          />
        </div>

        <div className="onboarding-v2-footnote">
          <Search size={13} />
          <span>
            Bing 自动搜索
            {settings?.basic?.search_enabled ? "已开启" : "默认关闭"}；
            可在设置中调整。
          </span>
          <span className="onboarding-v2-footnote-sep" aria-hidden="true">
            ·
          </span>
          <Lock size={13} />
          <span>
            另有 {lockedAiCount} 类需 AI、{lockedManualCount} 类需手动。
          </span>
        </div>
        {selected.size === 0 ? (
          <p className="onboarding-inline-warn">
            <AlertTriangle size={14} />
            未选择任何卡片任务，只会执行上方的领取动作。
          </p>
        ) : null}
      </div>
    );
  };

  const renderSchedule = () => (
    <div className="onboarding-step">
      <StepHead
        icon={CalendarClock}
        tone="mint"
        kicker="STEP 04 · RUNTIME"
        title="定好每天几点跑。"
        description="只有开启每日调度，程序才会按时间自动运行。"
      />
      <section
        className={`onboarding-runtime-card ${
          form.schedulerEnabled ? "is-on" : ""
        }`}
      >
        <div className="onboarding-runtime-head">
          <span className="onboarding-step-icon is-mint">
            <CalendarClock size={19} />
          </span>
          <div>
            <strong>每日自动调度</strong>
            <p>
              {firstRun
                ? "初始化期间不会自动跑；开启后从下一个计划时间开始。"
                : "关闭时仍可从总览手动运行。"}
            </p>
          </div>
          <Switch
            checked={Boolean(form.schedulerEnabled)}
            onChange={(value) => update("schedulerEnabled", value)}
            label="每日自动调度"
          />
        </div>
        <div className="onboarding-v2-schedule-grid">
          <label>
            <span>计划时间</span>
            <input
              type="time"
              value={form.runAt}
              onChange={(event) => update("runAt", event.target.value)}
              aria-invalid={!runAtValid}
            />
          </label>
          <label>
            <span>时区</span>
            <select
              value={form.timezone}
              onChange={(event) => update("timezone", event.target.value)}
            >
              {timezoneOptions.map(([value, label]) => (
                <option value={value} key={value}>
                  {label}
                </option>
              ))}
            </select>
          </label>
        </div>
        <p className="onboarding-v2-fineprint">
          <ShieldCheck size={13} />
          保存时不会立即运行；启用后从下一个计划时间开始，不补跑今天。
        </p>
      </section>

      <div className="onboarding-info-strip">
        <Leaf size={15} />
        <span>
          低功耗挂机与系统托盘可在总览页按需开启，教程不会自动启用。
        </span>
      </div>

      <div className="onboarding-v2-summary">
        <CheckCircle2 size={15} />
        <span>
          将保存 <strong>{form.mode === "advanced" ? "进阶 AI" : "基础模式"}</strong>
          {" · "}
          <strong>{form.taskTypes.length} 类任务</strong>
          {" · "}
          {form.schedulerEnabled ? `每天 ${form.runAt || "--:--"}` : "不开启调度"}
        </span>
      </div>

      {advancedBlocked ? (
        <p className="onboarding-inline-warn">
          <AlertTriangle size={14} />
          进阶 AI 缺少 API Key，请返回上一步填写或切回基础模式。
        </p>
      ) : null}
      {!runAtValid ? (
        <p className="onboarding-inline-warn">
          <AlertTriangle size={14} />
          请输入 24 小时制时间，例如 09:30。
        </p>
      ) : null}
    </div>
  );

  const renderStep = () => {
    if (step > 0 && loading) {
      return (
        <div className="onboarding-loading" key="loading">
          <Loader2 size={24} className="spin" />
          <strong>正在读取当前配置…</strong>
          <p>只读取本地设置，不会运行任务。</p>
        </div>
      );
    }
    if (step > 0 && loadError) {
      return (
        <div className="onboarding-load-error" key="error">
          <span className="onboarding-load-icon">
            <AlertTriangle size={22} />
          </span>
          <h3>无法读取当前配置</h3>
          <p>{loadError}</p>
          <div className="onboarding-load-actions">
            <button
              type="button"
              className="btn btn-primary"
              onClick={loadSettings}
            >
              <Loader2 size={16} />
              重新读取
            </button>
            <button type="button" className="btn btn-quiet" onClick={skip}>
              跳过教程
            </button>
          </div>
        </div>
      );
    }
    if (step === 0) return renderAccount();
    if (!form || !settings) {
      return (
        <div className="onboarding-loading" key="wait">
          <Loader2 size={24} className="spin" />
          <strong>正在准备教程…</strong>
        </div>
      );
    }
    if (STEPS[step].id === "mode") return renderMode();
    if (STEPS[step].id === "tasks") return renderTasks();
    return renderSchedule();
  };

  const nextDisabled =
    saving ||
    loading ||
    Boolean(loadError) ||
    !form ||
    (STEPS[step].id === "mode" && advancedBlocked);
  const canFinish =
    !saving &&
    !loading &&
    !loadError &&
    Boolean(form) &&
    !advancedBlocked &&
    scheduleValid;
  const lastStep = step === STEPS.length - 1;

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="onboarding-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.24 }}
        >
          <motion.div
            ref={dialogRef}
            className="onboarding-shell onboarding-v2"
            role="dialog"
            aria-modal="true"
            aria-labelledby="onboarding-title"
            tabIndex={-1}
            initial={{ opacity: 0, y: 24, scale: 0.985 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 18, scale: 0.99 }}
            transition={{ duration: 0.34, ease: [0.22, 1, 0.36, 1] }}
          >
            <aside className="onboarding-rail">
              <div className="onboarding-brand">
                <span className="onboarding-brand-mark">
                  <Zap size={19} strokeWidth={2.4} />
                </span>
                <span>
                  <strong>
                    Rewards <em>Pilot</em>
                  </strong>
                  <small>QUICK SETUP</small>
                </span>
              </div>
              <span className="onboarding-rail-kicker">首次运行 · 快速设置</span>
              <ol className="onboarding-steps">
                {STEPS.map((item, index) => {
                  const Icon = item.icon;
                  const active = index === step;
                  const done = index < step;
                  return (
                    <li
                      key={item.id}
                      className={`onboarding-step-nav ${
                        active ? "is-active" : ""
                      } ${done ? "is-done" : ""}`}
                      aria-current={active ? "step" : undefined}
                    >
                      <span className="onboarding-step-dot">
                        {done ? (
                          <Check size={13} strokeWidth={3} />
                        ) : (
                          <Icon size={14} />
                        )}
                      </span>
                      <span className="onboarding-step-nav-copy">
                        <strong>{item.label}</strong>
                        <small>{item.hint}</small>
                      </span>
                    </li>
                  );
                })}
              </ol>
              <div className="onboarding-rail-foot">
                <ShieldCheck size={15} />
                <p>每一步都可跳过；所有选项稍后都能在设置中修改。</p>
              </div>
            </aside>

            <section className="onboarding-stage">
              <div className="onboarding-stage-head">
                <span className="onboarding-stage-count">
                  STEP {String(step + 1).padStart(2, "0")}
                  <i>/ {String(STEPS.length).padStart(2, "0")}</i>
                </span>
                <span className="onboarding-stage-name">
                  {STEPS[step].label}
                </span>
                <button
                  type="button"
                  className="onboarding-close"
                  onClick={skip}
                  disabled={saving}
                  aria-label="关闭初始化教程"
                >
                  <X size={17} />
                </button>
              </div>

              <div className="onboarding-progress" aria-hidden="true">
                <motion.span
                  animate={{
                    width: `${((step + 1) / STEPS.length) * 100}%`,
                  }}
                  transition={{ duration: 0.4, ease: [0.22, 1, 0.36, 1] }}
                />
              </div>

              <div className="onboarding-scroll" ref={scrollRef}>
                <AnimatePresence mode="wait" initial={false}>
                  <motion.div
                    key={`${step}-${loading ? "loading" : "ready"}-${
                      loadError ? "error" : "ok"
                    }`}
                    initial={{ opacity: 0, x: direction * 22 }}
                    animate={{ opacity: 1, x: 0 }}
                    exit={{ opacity: 0, x: direction * -16 }}
                    transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
                  >
                    {renderStep()}
                  </motion.div>
                </AnimatePresence>
              </div>

              {saveError ? (
                <div className="onboarding-save-error">
                  <AlertTriangle size={15} />
                  <span>{saveError}</span>
                </div>
              ) : null}

              <footer className="onboarding-footer">
                <div className="onboarding-footer-left">
                  {step > 0 ? (
                    <button
                      type="button"
                      className="btn btn-quiet"
                      onClick={goBack}
                      disabled={saving}
                    >
                      <ArrowLeft size={16} />
                      上一步
                    </button>
                  ) : (
                    <span className="onboarding-footer-note">
                      4 步 · 约 1 分钟
                    </span>
                  )}
                </div>
                <div className="onboarding-footer-right">
                  <button
                    type="button"
                    className="btn btn-quiet"
                    onClick={skip}
                    disabled={saving}
                  >
                    {lastStep ? "不保存，跳过" : "跳过教程"}
                  </button>
                  {lastStep ? (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={goNext}
                      disabled={!canFinish}
                    >
                      {saving ? (
                        <Loader2 size={16} className="spin" />
                      ) : (
                        <Rocket size={16} />
                      )}
                      {saving ? "正在保存…" : "保存并进入"}
                    </button>
                  ) : (
                    <button
                      type="button"
                      className="btn btn-primary"
                      onClick={goNext}
                      disabled={nextDisabled}
                    >
                      下一步
                      <ArrowRight size={16} />
                    </button>
                  )}
                </div>
              </footer>
            </section>
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}
