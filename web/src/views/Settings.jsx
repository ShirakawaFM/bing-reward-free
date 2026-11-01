import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity,
  AlertTriangle,
  CalendarClock,
  Check,
  Compass,
  Copy,
  Cpu,
  Eye,
  EyeOff,
  Info,
  KeyRound,
  Leaf,
  ListChecks,
  Loader2,
  Power,
  RotateCcw,
  Save,
  ShieldCheck,
  Sparkles,
} from "lucide-react";
import { Modal, Spinner, Switch } from "../components/ui";
import LowPowerPanel from "../components/LowPowerPanel";
import TaskPicker from "../components/TaskPicker";
import { api } from "../lib/api";
import { withCurrentTimezone } from "../lib/timezones";

function toForm(settings) {
  return {
    general: {
      run_at: settings.general.run_at,
      timezone: settings.general.timezone,
      mode: settings.general.mode,
      headless: Boolean(settings.general.headless),
      catch_up: Boolean(settings.general.catch_up),
    },
    basic: {
      max_tasks: String(settings.basic.max_tasks),
      auto_claim: Boolean(settings.basic.auto_claim),
      search_enabled: Boolean(settings.basic.search_enabled),
      search_count: String(settings.basic.search_count),
      search_delay_min: String(settings.basic.search_delay_min),
      search_delay_max: String(settings.basic.search_delay_max),
      read_wait_seconds: String(settings.basic.read_wait_seconds),
      task_types: [...(settings.basic.task_types || [])],
    },
    advanced: {
      base_url: settings.advanced.base_url,
      model: settings.advanced.model,
      vision: Boolean(settings.advanced.vision),
      temperature: String(settings.advanced.temperature),
      max_steps: String(settings.advanced.max_steps),
      max_minutes: String(settings.advanced.max_minutes),
    },
  };
}

function validate(form) {
  if (!/^([01]?\d|2[0-3]):[0-5]\d$/.test(form.general.run_at || "")) {
    return "每日运行时间必须是 HH:MM 格式。";
  }
  if (!form.general.timezone) return "请选择时区。";
  const numbers = [
    [form.basic.max_tasks, "任务数量上限", 1, 30],
    [form.basic.search_count, "搜索次数", 0, 100],
    [form.basic.search_delay_min, "搜索最短间隔", 0.5, 120],
    [form.basic.search_delay_max, "搜索最长间隔", 0.5, 300],
    [form.basic.read_wait_seconds, "阅读等待", 1, 60],
    [form.advanced.temperature, "模型温度", 0, 2],
    [form.advanced.max_steps, "最大步数", 3, 120],
    [form.advanced.max_minutes, "最长运行分钟", 1, 60],
  ];
  for (const [value, label, min, max] of numbers) {
    const parsed = Number(value);
    if (String(value).trim() === "" || !Number.isFinite(parsed)) {
      return `${label} 必须是数字。`;
    }
    if (parsed < min || parsed > max) {
      return `${label} 需要在 ${min} – ${max} 之间。`;
    }
  }
  if (Number(form.basic.search_delay_max) < Number(form.basic.search_delay_min)) {
    return "搜索最长间隔不能小于最短间隔。";
  }
  if (!/^https?:\/\/.+/i.test(form.advanced.base_url || "")) {
    return "API 地址需要以 http:// 或 https:// 开头。";
  }
  if (!(form.advanced.model || "").trim()) return "请填写模型名称。";
  return null;
}

function Field({ label, hint, children, wide = false }) {
  return (
    <label className={`field ${wide ? "is-wide" : ""}`}>
      <span className="field-label">{label}</span>
      {children}
      {hint ? <span className="field-hint">{hint}</span> : null}
    </label>
  );
}

function ToggleRow({ icon: Icon, title, hint, checked, onChange, disabled, tone = "" }) {
  return (
    <div className={`toggle-row ${tone ? `is-${tone}` : ""} ${disabled ? "is-disabled" : ""}`}>
      {Icon ? (
        <span className="toggle-glyph">
          <Icon size={16} />
        </span>
      ) : null}
      <div className="toggle-copy">
        <strong>{title}</strong>
        <p>{hint}</p>
      </div>
      <Switch checked={checked} onChange={onChange} disabled={disabled} label={title} />
    </div>
  );
}

function SettingsSection({ icon: Icon, tone, kicker, title, description, children, badge }) {
  return (
    <section className="card settings-section">
      <div className="section-head">
        <span className={`head-glyph is-${tone}`}>
          <Icon size={18} />
        </span>
        <div>
          <span className="section-kicker">{kicker}</span>
          <h3>{title}</h3>
          <p>{description}</p>
        </div>
        {badge ? <span className="section-badge">{badge}</span> : null}
      </div>
      <div className="section-content">{children}</div>
    </section>
  );
}

export default function Settings({
  state,
  focusRequest = null,
  onSaved,
  onToast,
  onShutdown,
  onPowerChanged,
  onShowOnboarding,
}) {
  const [settings, setSettings] = useState(null);
  const [catalog, setCatalog] = useState(null);
  const [form, setForm] = useState(null);
  const [baseline, setBaseline] = useState(null);
  const [loading, setLoading] = useState(true);
  const [loadError, setLoadError] = useState("");
  const [saving, setSaving] = useState(false);
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [clearKey, setClearKey] = useState(false);
  const [test, setTest] = useState({ state: "idle" });
  const [confirmExit, setConfirmExit] = useState(false);
  const [exiting, setExiting] = useState(false);
  const [powerOverride, setPowerOverride] = useState(null);

  const load = useCallback(async () => {
    setLoading(true);
    setLoadError("");
    try {
      const data = await api.settings();
      setSettings(data.settings);
      setCatalog(data.task_catalog || null);
      const next = toForm(data.settings);
      setForm(next);
      setBaseline(next);
      setApiKey("");
      setClearKey(false);
    } catch (error) {
      setLoadError(error.message);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    load();
  }, [load]);

  useEffect(() => {
    if (
      powerOverride &&
      state?.power &&
      Boolean(state.power.enabled) === Boolean(powerOverride.enabled)
    ) {
      setPowerOverride(null);
    }
  }, [state?.power, powerOverride]);

  const powerState = powerOverride || state?.power || {};

  const dirty = useMemo(() => {
    if (!form || !baseline) return false;
    return (
      JSON.stringify(form) !== JSON.stringify(baseline) ||
      apiKey.trim().length > 0 ||
      clearKey
    );
  }, [form, baseline, apiKey, clearKey]);

  const update = (section, key, value) => {
    setForm((current) => ({
      ...current,
      [section]: { ...current[section], [key]: value },
    }));
  };

  const toggleTask = (item) => {
    if (item.field === "auto_claim") {
      update("basic", "auto_claim", !form.basic.auto_claim);
      return;
    }
    if (item.field === "search_enabled") {
      update("basic", "search_enabled", !form.basic.search_enabled);
      return;
    }
    if (!catalog) return;
    const current = new Set(form.basic.task_types || []);
    if (current.has(item.id)) current.delete(item.id);
    else current.add(item.id);
    update(
      "basic",
      "task_types",
      catalog.basic_card_task_ids.filter((id) => current.has(id)),
    );
  };

  const selectAllTasks = () => {
    if (!catalog) return;
    update("basic", "task_types", [...catalog.basic_card_task_ids]);
  };

  const recommendTasks = () => {
    if (!catalog) return;
    update("basic", "task_types", [...catalog.default_task_types]);
  };

  const reset = () => {
    if (!baseline) return;
    setForm(baseline);
    setApiKey("");
    setClearKey(false);
    onToast({ tone: "info", title: "已还原", message: "未保存的更改已撤销。" });
  };

  const save = async () => {
    if (!form) return;
    const problem = validate(form);
    if (problem) {
      onToast({ tone: "error", title: "设置未通过校验", message: problem });
      return;
    }
    setSaving(true);
    try {
      const payload = {
        general: {
          run_at: form.general.run_at,
          timezone: form.general.timezone,
          mode: form.general.mode,
          headless: form.general.headless,
          catch_up: form.general.catch_up,
        },
        basic: {
          max_tasks: Number(form.basic.max_tasks),
          auto_claim: form.basic.auto_claim,
          search_enabled: form.basic.search_enabled,
          search_count: Number(form.basic.search_count),
          search_delay_min: Number(form.basic.search_delay_min),
          search_delay_max: Number(form.basic.search_delay_max),
          read_wait_seconds: Number(form.basic.read_wait_seconds),
          task_types: [...form.basic.task_types],
        },
        advanced: {
          base_url: form.advanced.base_url.trim(),
          model: form.advanced.model.trim(),
          vision: form.advanced.vision,
          temperature: Number(form.advanced.temperature),
          max_steps: Number(form.advanced.max_steps),
          max_minutes: Number(form.advanced.max_minutes),
        },
      };
      if (apiKey.trim()) payload.advanced.api_key = apiKey.trim();
      if (clearKey) payload.advanced.clear_api_key = true;

      const data = await api.saveSettings(payload);
      setSettings(data.settings);
      if (data.task_catalog) setCatalog(data.task_catalog);
      const next = toForm(data.settings);
      setForm(next);
      setBaseline(next);
      setApiKey("");
      setClearKey(false);
      onSaved?.(data.settings);
      onToast({
        tone: "success",
        title: "设置已保存",
        message: state?.scheduler?.running
          ? "配置文件已原子写入，每日调度已按新配置重启。"
          : "配置文件已原子写入，新参数已生效。",
      });
    } catch (error) {
      onToast({ tone: "error", title: "保存失败", message: error.message });
    } finally {
      setSaving(false);
    }
  };

  const runSelftest = async () => {
    setTest({ state: "running" });
    try {
      const result = await api.selftest();
      setTest({
        state: "ok",
        message: result.message,
        ms: result.ms,
        channel: result.channel,
      });
      onToast({
        tone: "success",
        title: "环境自检通过",
        message: `${result.channel} · ${result.ms} ms`,
      });
    } catch (error) {
      setTest({ state: "error", message: error.message });
      onToast({ tone: "error", title: "环境自检失败", message: error.message });
    }
  };

  const handleExit = async () => {
    setExiting(true);
    try {
      await onShutdown();
    } catch (error) {
      onToast({ tone: "error", title: "退出失败", message: error.message });
      setExiting(false);
    }
  };

  const copyPath = async () => {
    try {
      await navigator.clipboard.writeText(settings.path);
      onToast({ tone: "success", title: "路径已复制", message: settings.path });
    } catch {
      onToast({ tone: "error", title: "复制失败", message: "请手动选择路径复制。" });
    }
  };

  if (loading) {
    return (
      <div className="view settings-view">
        <div className="settings-skeleton">
          <div className="skeleton skeleton-bar" />
          <div className="skeleton-grid">
            <div className="skeleton skeleton-panel" />
            <div className="skeleton skeleton-panel" />
          </div>
        </div>
      </div>
    );
  }

  if (loadError || !form || !settings) {
    return (
      <div className="view settings-view">
        <section className="card load-error">
          <span className="load-error-icon">
            <AlertTriangle size={22} />
          </span>
          <h3>无法读取配置</h3>
          <p>{loadError || "配置文件暂时不可用。"}</p>
          <button type="button" className="btn btn-primary" onClick={load}>
            <RotateCcw size={16} />
            重试
          </button>
        </section>
      </div>
    );
  }

  const keyConfigured = settings.advanced.api_key_set;
  const keyWillClear = clearKey;
  const visionSupported = !/api\.deepseek\.com/i.test(form.advanced.base_url);
  const jobRunning = Boolean(state?.job?.running);
  const timezoneOptions = withCurrentTimezone(form.general.timezone);

  return (
    <div className="view settings-view">
      <section className="card settings-hero">
        <div className="settings-hero-copy">
          <span className="section-kicker">CONFIGURATION</span>
          <h2>配置中心</h2>
          <p>
            所有设置保存在本地
            <code className="inline.path">{settings.path}</code>
          </p>
          {jobRunning ? (
            <span className="settings-running">
              <Loader2 size={13} className="spin" />
              任务运行中，新配置将在下一次运行时生效
            </span>
          ) : null}
        </div>
        <div className="settings-hero-actions">
          {dirty ? (
            <span className="dirty-badge">
              <span className="dirty-dot" />
              有未保存更改
            </span>
          ) : (
            <span className="saved-badge">
              <Check size={13} />
              已同步
            </span>
          )}
          <button
            type="button"
            className="btn btn-quiet"
            onClick={reset}
            disabled={!dirty || saving}
          >
            <RotateCcw size={16} />
            还原
          </button>
          <button
            type="button"
            className="btn btn-primary"
            onClick={save}
            disabled={!dirty || saving}
          >
            {saving ? <Spinner size={16} /> : <Save size={16} />}
            {saving ? "保存中…" : "保存设置"}
          </button>
        </div>
      </section>

      <div className="settings-layout">
        <div className="settings-main">
          <SettingsSection
            icon={CalendarClock}
            tone="mint"
            kicker="SCHEDULE"
            title="常规与调度"
            description="决定什么时候运行，以及以哪种方式打开浏览器。"
            badge={form.general.mode === "advanced" ? "ADVANCED" : "BASIC"}
          >
            <div className="field-grid">
              <Field label="每日运行时间" hint="24 小时制，本地时区">
                <input
                  type="time"
                  value={form.general.run_at}
                  onChange={(event) => update("general", "run_at", event.target.value)}
                />
              </Field>
              <Field label="时区" hint="程序按此时区判断“今天”和补跑">
                <select
                  value={form.general.timezone}
                  onChange={(event) => update("general", "timezone", event.target.value)}
                >
                  {timezoneOptions.map(([value, label]) => (
                    <option value={value} key={value}>
                      {label}
                    </option>
                  ))}
                </select>
              </Field>
              <Field label="默认执行模式" wide hint="在总览页仍可为单次运行临时切换">
                <div className="mode-options">
                  <button
                    type="button"
                    className={`mode-option ${form.general.mode === "basic" ? "is-active" : ""}`}
                    onClick={() => update("general", "mode", "basic")}
                  >
                    <ShieldCheck size={17} />
                    <span>
                      <strong>基础模式</strong>
                      <small>内置规则，不需要大模型</small>
                    </span>
                  </button>
                  <button
                    type="button"
                    className={`mode-option ${form.general.mode === "advanced" ? "is-active" : ""}`}
                    onClick={() => update("general", "mode", "advanced")}
                  >
                    <Sparkles size={17} />
                    <span>
                      <strong>进阶 AI</strong>
                      <small>元素索引 + DeepSeek 决策</small>
                    </span>
                  </button>
                </div>
              </Field>
            </div>

            <div className="toggle-stack">
              <ToggleRow
                icon={CalendarClock}
                title="错过时点后补跑"
                hint="启动时如果今天已过执行时间且尚未运行，就立即补跑一次。"
                checked={form.general.catch_up}
                onChange={(value) => update("general", "catch_up", value)}
              />
              <ToggleRow
                icon={EyeOff}
                title="无头运行浏览器"
                hint="无头模式更快，但遇到验证码时不易察觉。首次使用建议关闭。"
                checked={form.general.headless}
                onChange={(value) => update("general", "headless", value)}
              />
            </div>
          </SettingsSection>

          <SettingsSection
            icon={ListChecks}
            tone="sky"
            kicker="BASIC MODE"
            title="基础任务"
            description="扫描仪表盘任务卡片，完成问答并领取可领取的奖励。"
          >
            <div className="field-grid">
              <Field label="每轮任务上限" hint="1 – 30，越小越保守">
                <input
                  type="number"
                  min="1"
                  max="30"
                  value={form.basic.max_tasks}
                  onChange={(event) => update("basic", "max_tasks", event.target.value)}
                />
              </Field>
              <Field label="页面阅读等待（秒）" hint="给任务页面留出加载时间">
                <input
                  type="number"
                  min="1"
                  max="60"
                  step="1"
                  value={form.basic.read_wait_seconds}
                  onChange={(event) =>
                    update("basic", "read_wait_seconds", event.target.value)
                  }
                />
              </Field>
            </div>

            <TaskPicker
              catalog={catalog}
              selectedIds={form.basic.task_types}
              autoClaim={form.basic.auto_claim}
              searchEnabled={form.basic.search_enabled}
              focusRequest={focusRequest}
              onToggle={toggleTask}
              onSelectAll={selectAllTasks}
              onRecommend={recommendTasks}
              disabled={saving}
            />

            {form.basic.search_enabled ? (
              <div className="field-grid reveal-grid">
                <Field label="搜索次数" hint="0 – 100">
                  <input
                    type="number"
                    min="0"
                    max="100"
                    value={form.basic.search_count}
                    onChange={(event) =>
                      update("basic", "search_count", event.target.value)
                    }
                  />
                </Field>
                <Field label="最短间隔（秒）">
                  <input
                    type="number"
                    min="0.5"
                    step="0.5"
                    value={form.basic.search_delay_min}
                    onChange={(event) =>
                      update("basic", "search_delay_min", event.target.value)
                    }
                  />
                </Field>
                <Field label="最长间隔（秒）">
                  <input
                    type="number"
                    min="0.5"
                    step="0.5"
                    value={form.basic.search_delay_max}
                    onChange={(event) =>
                      update("basic", "search_delay_max", event.target.value)
                    }
                  />
                </Field>
              </div>
            ) : null}
          </SettingsSection>

          <SettingsSection
            icon={Leaf}
            tone="mint"
            kicker="LOW POWER · 7 DAYS"
            title="低功耗挂机"
            description="让整机进入节能状态并保持一周待命，同时只保留一个 Rewards Pilot。"
            badge={powerState.enabled ? "ECO ON" : "ECO OFF"}
          >
            <LowPowerPanel
              power={powerState}
              jobRunning={jobRunning}
              onToast={onToast}
              onChanged={(next) => {
                setPowerOverride(next);
                onPowerChanged?.();
              }}
            />
          </SettingsSection>

          <SettingsSection
            icon={Sparkles}
            tone="violet"
            kicker="ADVANCED MODE"
            title="进阶 AI"
            description="把编号后的页面元素交给兼容 OpenAI 接口的模型，由它选择下一步操作。"
            badge={keyConfigured && !keyWillClear ? "KEY READY" : "NO KEY"}
          >
            <div className="field-grid">
              <Field label="API 地址" wide hint="支持 OpenAI 兼容接口，默认 DeepSeek">
                <input
                  type="url"
                  value={form.advanced.base_url}
                  onChange={(event) =>
                    update("advanced", "base_url", event.target.value)
                  }
                  spellCheck="false"
                />
              </Field>
              <Field label="模型名称">
                <input
                  type="text"
                  value={form.advanced.model}
                  onChange={(event) => update("advanced", "model", event.target.value)}
                  spellCheck="false"
                />
              </Field>
              <Field label="温度" hint="0 最稳定，建议保持 0">
                <input
                  type="number"
                  min="0"
                  max="2"
                  step="0.1"
                  value={form.advanced.temperature}
                  onChange={(event) =>
                    update("advanced", "temperature", event.target.value)
                  }
                />
              </Field>
              <Field label="最大步数" hint="3 – 120">
                <input
                  type="number"
                  min="3"
                  max="120"
                  value={form.advanced.max_steps}
                  onChange={(event) =>
                    update("advanced", "max_steps", event.target.value)
                  }
                />
              </Field>
              <Field label="最长运行（分钟）" hint="1 – 60">
                <input
                  type="number"
                  min="1"
                  max="60"
                  value={form.advanced.max_minutes}
                  onChange={(event) =>
                    update("advanced", "max_minutes", event.target.value)
                  }
                />
              </Field>
            </div>

            <div className="key-panel">
              <div className="key-panel-head">
                <span className="key-glyph">
                  <KeyRound size={16} />
                </span>
                <div>
                  <strong>DeepSeek API Key</strong>
                  <p>
                    {keyConfigured
                      ? "Key 已保存在本地配置文件，界面不会回显。"
                      : "尚未配置。也可以在环境变量 DEEPSEEK_API_KEY 中提供。"}
                  </p>
                </div>
                <span className={`key-status ${keyConfigured && !keyWillClear ? "is-ok" : ""}`}>
                  {keyWillClear ? "将清除" : keyConfigured ? "已配置" : "未配置"}
                </span>
              </div>
              <div className="key-input-row">
                <div className="input-wrap">
                  <KeyRound size={15} />
                  <input
                    type={showKey ? "text" : "password"}
                    value={apiKey}
                    placeholder={keyConfigured ? "留空保持不变 · 输入新 Key 可替换" : "sk-..."}
                    onChange={(event) => {
                      setApiKey(event.target.value);
                      if (event.target.value) setClearKey(false);
                    }}
                    disabled={clearKey}
                    autoComplete="off"
                    spellCheck="false"
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
                {keyConfigured ? (
                  <button
                    type="button"
                    className={`btn btn-subtle ${clearKey ? "is-danger" : ""}`}
                    onClick={() => {
                      setClearKey((value) => !value);
                      setApiKey("");
                    }}
                  >
                    {clearKey ? "取消清除" : "清除 Key"}
                  </button>
                ) : null}
              </div>
              <p className="key-note">
                Key 仅写入本机 config.toml，并只发送到你填写的 API 地址。截图与日志不会记录 Key。
              </p>
            </div>

            <div className="toggle-stack">
              <ToggleRow
                icon={Eye}
                title="向模型发送截图"
                hint={
                  visionSupported
                    ? "当前 API 地址可能支持视觉模型；开启后会随请求发送压缩截图。"
                    : "DeepSeek 官方接口为纯文本模型，此开关不会生效，页面元素索引仍会照常发送。"
                }
                checked={form.advanced.vision}
                onChange={(value) => update("advanced", "vision", value)}
                tone={form.advanced.vision && !visionSupported ? "warn" : ""}
              />
            </div>
          </SettingsSection>
        </div>

        <aside className="settings-aside">
          <section className="card aside-card">
            <div className="aside-head">
              <Cpu size={16} />
              <h3>运行环境</h3>
            </div>
            <dl className="env-list">
              <div>
                <dt>浏览器</dt>
                <dd>{settings.general.browser_channel || "内置 Chromium"}</dd>
              </div>
              <div>
                <dt>运行方式</dt>
                <dd>{form.general.headless ? "无头" : "窗口可见"}</dd>
              </div>
              <div>
                <dt>低功耗挂机</dt>
                <dd className={powerState.enabled ? "is-eco" : ""}>
                  {powerState.enabled ? "已开启" : "未开启"}
                </dd>
              </div>
              <div>
                <dt>目标站点</dt>
                <dd className="is-link">rewards.bing.com</dd>
              </div>
              <div>
                <dt>版本</dt>
                <dd>Rewards Pilot {state?.version || ""}</dd>
              </div>
            </dl>
            <div className="path-box">
              <span>配置文件</span>
              <code>{settings.path}</code>
              <button type="button" className="copy-btn" onClick={copyPath}>
                <Copy size={14} />
                复制
              </button>
            </div>
            <p className="aside-note">
              保存设置会先校验再原子替换配置；若每日调度正在运行，会按新配置自动重启。
            </p>
          </section>

          <section className="card aside-card selftest-card">
            <div className="aside-head">
              <Activity size={16} />
              <h3>环境自检</h3>
            </div>
            <p className="aside-copy">
              启动一次无头 Edge 并执行两条脚本，只验证 Playwright 环境，不登录、不访问账号。
            </p>
            <button
              type="button"
              className="btn btn-subtle btn-block"
              onClick={runSelftest}
              disabled={test.state === "running" || jobRunning}
            >
              {test.state === "running" ? (
                <Spinner size={15} />
              ) : (
                <Activity size={15} />
              )}
              {test.state === "running" ? "自检中…" : "运行环境自检"}
            </button>
            {test.state !== "idle" && test.state !== "running" ? (
              <div className={`selftest-result is-${test.state}`}>
                {test.state === "ok" ? <Check size={15} /> : <AlertTriangle size={15} />}
                <div>
                  <strong>{test.state === "ok" ? "环境正常" : "自检未通过"}</strong>
                  <p>
                    {test.message}
                    {test.ms ? ` · ${test.ms} ms` : ""}
                  </p>
                </div>
              </div>
            ) : null}
            {jobRunning ? <p className="aside-note">任务运行中，结束后才能自检。</p> : null}
          </section>

          <section className="card aside-card guide-card">
            <div className="aside-head">
              <Compass size={16} />
              <h3>初始化教程</h3>
            </div>
            <p className="aside-copy">
              四步快速设置：登录、模式、任务与运行时间。每一步都可跳过，教程不会自动运行任务。
            </p>
            <button
              type="button"
              className="btn btn-subtle btn-block"
              onClick={onShowOnboarding}
            >
              <Compass size={15} />
              重新打开初始化教程
            </button>
            <p className="aside-note">
              {state?.onboarding?.seen
                ? state.onboarding.action === "skipped"
                  ? "教程已跳过；重看时以当前配置为起点，只有最后一步才会保存。"
                  : "教程已完成；重看时以当前配置为起点，只有最后一步才会保存。"
                : "教程尚未完成，下次启动时会再次出现。"}
            </p>
          </section>

          <section className="card aside-card privacy-card">
            <div className="aside-head">
              <ShieldCheck size={16} />
              <h3>数据边界</h3>
            </div>
            <ul>
              <li>登录态仅保存在本机 .browser-profile，需要你的授权才能复用。</li>
              <li>
                运行截图可能包含账号信息，位于 state/screenshots，请勿直接分享。
              </li>
              <li>基础模式不会向任何大模型服务发送页面数据。</li>
            </ul>
            <div className="privacy-tag">
              <Info size={13} />
              仅监听 127.0.0.1，自带随机访问令牌
            </div>
          </section>

          <section className="card aside-card danger-card">
            <div className="aside-head">
              <Power size={16} />
              <h3>退出应用</h3>
            </div>
            <p className="aside-copy">
              关闭界面窗口也会自动结束后台服务。正在运行的任务需要先等待完成。
            </p>
            <button
              type="button"
              className="btn btn-danger btn-block"
              onClick={() => setConfirmExit(true)}
              disabled={jobRunning}
            >
              <Power size={15} />
              {jobRunning ? "任务运行中，暂不能退出" : "退出 Rewards Pilot"}
            </button>
          </section>
        </aside>
      </div>

      {dirty ? (
        <div className="save-dock">
          <div className="save-dock-copy">
            <span className="dirty-dot" />
            配置有未保存的更改
          </div>
          <div className="save-dock-actions">
            <button
              type="button"
              className="btn btn-quiet"
              onClick={reset}
              disabled={saving}
            >
              还原
            </button>
            <button
              type="button"
              className="btn btn-primary"
              onClick={save}
              disabled={saving}
            >
              {saving ? <Spinner size={15} /> : <Save size={15} />}
              {saving ? "保存中…" : "保存设置"}
            </button>
          </div>
        </div>
      ) : null}

      <Modal
        open={confirmExit}
        onClose={() => {
          if (!exiting) setConfirmExit(false);
        }}
        className="confirm-dialog"
        labelledBy="exit-title"
      >
        <div className="confirm-icon">
          <Power size={24} />
        </div>
        <h2 id="exit-title">退出 Rewards Pilot？</h2>
        <p>
          每日调度会立即停止，本地控制台将关闭。下次需要手动重新启动程序。
          登录态与配置会保留在本机。
        </p>
        <div className="confirm-actions">
          <button
            type="button"
            className="btn btn-quiet"
            onClick={() => setConfirmExit(false)}
            disabled={exiting}
          >
            继续使用
          </button>
          <button
            type="button"
            className="btn btn-danger"
            onClick={handleExit}
            disabled={exiting}
          >
            {exiting ? <Spinner size={15} /> : <Power size={15} />}
            {exiting ? "正在退出…" : "确认退出"}
          </button>
        </div>
      </Modal>
    </div>
  );
}
