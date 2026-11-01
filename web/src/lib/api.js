const query = new URLSearchParams(window.location.search);

export const APP_TOKEN =
  window.__APP_TOKEN__ || query.get("token") || "";

export const APP_VERSION =
  window.__APP_VERSION__ || "1.0.1";

async function request(path, { method = "GET", body, signal } = {}) {
  const headers = { "X-App-Token": APP_TOKEN };
  if (body !== undefined) headers["Content-Type"] = "application/json";

  let response;
  try {
    response = await fetch(path, {
      method,
      headers,
      body: body !== undefined ? JSON.stringify(body) : undefined,
      cache: "no-store",
      signal,
    });
  } catch (cause) {
    if (cause && cause.name === "AbortError") throw cause;
    const error = new Error("无法连接本地服务，请确认应用仍在运行。");
    error.cause = cause;
    throw error;
  }

  let data = null;
  try {
    data = await response.json();
  } catch {
    data = null;
  }

  if (!response.ok) {
    const error = new Error(
      (data && data.error) || `请求失败（HTTP ${response.status}）`,
    );
    error.status = response.status;
    error.payload = data;
    throw error;
  }
  return data;
}

export const api = {
  state: (signal) => request("/api/state", { signal }),
  logs: (after = 0, limit = 300, signal) =>
    request(`/api/logs?after=${encodeURIComponent(after)}&limit=${limit}`, {
      signal,
    }),
  settings: (signal) => request("/api/settings", { signal }),
  saveSettings: (payload) =>
    request("/api/settings", { method: "PUT", body: payload }),
  onboarding: (signal) => request("/api/onboarding", { signal }),
  completeOnboarding: (action = "completed") =>
    request("/api/onboarding/complete", {
      method: "POST",
      body: { action },
    }),
  run: (mode) => request("/api/run", { method: "POST", body: { mode } }),
  loginStart: () => request("/api/login/start", { method: "POST" }),
  loginFinish: () => request("/api/login/finish", { method: "POST" }),
  loginCancel: () => request("/api/login/cancel", { method: "POST" }),
  schedulerStart: (catchUp) =>
    request("/api/scheduler/start", {
      method: "POST",
      body: catchUp === undefined ? undefined : { catch_up: Boolean(catchUp) },
    }),
  schedulerStop: () => request("/api/scheduler/stop", { method: "POST" }),
  selftest: () => request("/api/selftest", { method: "POST" }),
  screenshots: (signal) => request("/api/screenshots", { signal }),
  powerApps: () => request("/api/power/apps"),
  powerActivate: (closeApps = []) =>
    request("/api/power/activate", {
      method: "POST",
      body: { close_apps: closeApps },
    }),
  powerDeactivate: () => request("/api/power/deactivate", { method: "POST" }),
  shutdown: () => request("/api/shutdown", { method: "POST" }),
};

export function withToken(url) {
  if (!url) return url;
  const separator = url.includes("?") ? "&" : "?";
  return `${url}${separator}token=${encodeURIComponent(APP_TOKEN)}`;
}
