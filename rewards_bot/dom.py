from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import urlparse

from playwright.sync_api import Page

OBSERVE_JS = r"""
() => {
  const MAX_ELEMENTS = 140;
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-qbot-id]').forEach((el) => el.removeAttribute('data-qbot-id'));

  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 3 || rect.height < 3) return false;
    const style = getComputedStyle(el);
    if (style.visibility === 'hidden' || style.display === 'none') return false;
    if (Number(style.opacity || '1') < 0.05) return false;
    return true;
  };

  const regionOf = (el) => {
    if (el.closest('[role="dialog"], dialog[open], [aria-modal="true"]')) return 'dialog';
    if (el.closest('header, [role="banner"]')) return 'header';
    if (el.closest('footer, [role="contentinfo"]')) return 'footer';
    if (el.closest('nav, [role="navigation"]')) return 'nav';
    if (el.closest('main, [role="main"]')) return 'main';
    return 'other';
  };
  const regionRank = {main: 0, dialog: 0, other: 1, header: 2, nav: 3, footer: 4};
  const selector = [
    'a[href]', 'button', 'input:not([type="hidden"])', 'select', 'textarea',
    'summary', '[role="button"]', '[role="link"]', '[role="radio"]',
    '[role="checkbox"]', '[role="tab"]', '[role="menuitem"]', '[role="option"]',
    '[onclick]', '[tabindex]:not([tabindex="-1"])'
  ].join(',');

  const raw = [];
  const seen = new Set();
  for (const el of document.querySelectorAll(selector)) {
    if (seen.has(el)) continue;
    seen.add(el);
    if (!visible(el)) continue;
    if (el.disabled) continue;
    if ((el.getAttribute('aria-disabled') || '').toLowerCase() === 'true') continue;

    const tag = el.tagName.toLowerCase();
    if (tag === 'input' && el.type === 'hidden') continue;
    if (tag === 'input' && el.type === 'password') continue;

    const aria = norm(el.getAttribute('aria-label') || el.getAttribute('title') || '');
    let text = norm(el.innerText || el.textContent || '');
    if (tag === 'input') {
      let labels = '';
      try {
        labels = norm(Array.from(el.labels || []).map((label) => label.innerText).join(' '));
      } catch (err) {}
      text = norm(labels || aria || el.value || el.placeholder || el.type);
    }
    if (text.length > 160) text = text.slice(0, 160) + '…';
    if (!text && !aria) {
      if (!['radio', 'checkbox'].includes(el.type)) continue;
    }

    const rect = el.getBoundingClientRect();
    let href = '';
    try {
      if (typeof el.href === 'string' && el.href && !el.href.startsWith('javascript:')) {
        const parsed = new URL(el.href, location.href);
        if (parsed.protocol === 'http:' || parsed.protocol === 'https:') {
          href = (parsed.host + parsed.pathname + parsed.search).slice(0, 220);
        }
      }
    } catch (err) {}

    const region = regionOf(el);
    raw.push({
      el: el,
      tag: tag,
      text: text,
      aria: aria && aria !== text ? aria : '',
      href: href,
      type: (el.getAttribute('type') || '').toLowerCase(),
      role: (el.getAttribute('role') || '').toLowerCase(),
      checked: !!(el.checked || el.getAttribute('aria-checked') === 'true' || el.getAttribute('aria-selected') === 'true'),
      region: region,
      rank: regionRank[region] === undefined ? 1 : regionRank[region],
      top: Math.round(rect.top + window.scrollY)
    });
  }

  raw.sort((a, b) => (a.rank - b.rank) || (a.top - b.top));
  const elements = [];
  for (const item of raw.slice(0, MAX_ELEMENTS)) {
    const id = elements.length;
    item.el.setAttribute('data-qbot-id', String(id));
    const rect = item.el.getBoundingClientRect();
    elements.push({
      id: id,
      tag: item.tag,
      region: item.region,
      role: item.role,
      text: item.text,
      aria: item.aria,
      href: item.href,
      type: item.type,
      checked: item.checked,
      in_viewport: rect.bottom > 0 && rect.top < window.innerHeight
    });
  }

  const main = document.querySelector('main, [role="main"]') || document.body;
  let pageText = (main.innerText || '').replace(/\s+/g, ' ').trim();
  if (pageText.length > 3000) pageText = pageText.slice(0, 3000) + '…';
  const headings = Array.from(document.querySelectorAll('h1,h2,h3'))
    .map((h) => norm(h.innerText))
    .filter(Boolean)
    .slice(0, 20);

  return {
    url: location.href,
    title: document.title,
    headings: headings,
    text: pageText,
    scroll_y: Math.round(window.scrollY),
    document_height: Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement.scrollHeight),
    viewport: {width: window.innerWidth, height: window.innerHeight},
    elements: elements
  };
}
"""


def observe(page: Page) -> dict[str, Any]:
    data = page.evaluate(OBSERVE_JS)
    try:
        data["tabs"] = len(page.context.pages)
    except Exception:
        data["tabs"] = 1
    return data


def format_observation(obs: dict[str, Any]) -> str:
    """压缩观察结果，减少发送给模型的 token。"""
    payload: dict[str, Any] = {
        "step_page": {
            "url": obs.get("url", ""),
            "title": obs.get("title", ""),
            "headings": obs.get("headings", []),
            "scroll_y": obs.get("scroll_y", 0),
            "document_height": obs.get("document_height", 0),
            "viewport": obs.get("viewport", {}),
            "tabs": obs.get("tabs", 1),
        },
        "page_text": obs.get("text", ""),
        "elements": [],
    }
    for item in obs.get("elements", []):
        compact: dict[str, Any] = {"id": item["id"], "tag": item["tag"]}
        for key in ("region", "role", "type", "text", "aria", "href"):
            value = item.get(key)
            if value:
                compact[key] = value
        if item.get("checked"):
            compact["checked"] = True
        if item.get("in_viewport"):
            compact["in_viewport"] = True
        payload["elements"].append(compact)
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def host_allowed(url_or_host: str, allowed_hosts: list[str]) -> bool:
    if not url_or_host:
        return False
    value = url_or_host.strip()
    if "://" in value:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme not in {"http", "https"}:
            return False
    else:
        host = value.split("/")[0].split(":")[0].lower()
    return any(host == allowed or host.endswith("." + allowed) for allowed in allowed_hosts)


_DENY_LABEL_RE = re.compile(
    r"^\s*(?:"
    r"兑换|兌換|换购|"
    r"redeem|"
    r"购买|購買|buy|purchase|"
    r"付款|支付|充值|top\s?up|"
    r"设置|設定|账户设置|账号设置|settings?|"
    r"退出登录|退出登入|退出|登出|注销|登出账号|"
    r"sign\s?out|log\s?out|"
    r"删除账号|删除账户|删除|delete|"
    r"隐私声明|隐私|privacy|"
    r"payment|付款方式|"
    r"礼品卡|禮品卡|gift\s?cards?"
    r")(?:\s|$|[:：]|\(|（|[\u4e00-\u9fff]).*",
    re.IGNORECASE,
)

_DENY_HREF_RE = re.compile(
    r"/(?:redeem|shop|catalog|checkout|payment|billing|settings|privacy|account)(?:/|$|[?#])",
    re.IGNORECASE,
)


def _clean_label(text: str) -> str:
    text = re.sub(r"\s+", " ", text or "").strip().lower()
    # 去掉按钮前后常见的箭头/项目符号，保留文字本身。
    text = re.sub(r"^[\s>›»→\u200b·•]+|[\s<‹«←\u200b·•]+$", "", text)
    return text


def click_block_reason(
    text: str,
    href: str,
    allowed_hosts: list[str],
    *,
    input_type: str = "",
) -> str | None:
    """点击前最后一道安全护栏。返回 None 表示允许。"""
    if input_type == "password":
        return "不允许点击密码输入框"
    label = _clean_label(text)
    if label and _DENY_LABEL_RE.match(label):
        return f"元素文字命中高风险操作：{label[:60]}"
    if href:
        parsed = urlparse(href)
        if parsed.scheme in {"http", "https"}:
            if not host_allowed(href, allowed_hosts):
                return f"链接域名不在允许列表：{parsed.hostname}"
            if _DENY_HREF_RE.search(parsed.path or ""):
                return f"链接路径指向兑换/设置等高风险页面：{parsed.path}"
    return None


def is_dashboard_url(url: str, dashboard_url: str) -> bool:
    try:
        current = urlparse(url)
        dashboard = urlparse(dashboard_url)
        return (
            (current.hostname or "").lower() == (dashboard.hostname or "").lower()
            and (current.path or "/").rstrip("/") == (dashboard.path or "/").rstrip("/")
        )
    except ValueError:
        return False


REWARDS_HOME_PATHS = {"/dashboard", "/earn"}


def is_rewards_home_url(url: str, base_url: str) -> bool:
    """Rewards 新版 /earn 与旧版 /dashboard 都算任务主页，兼容服务端重定向。"""

    try:
        current = urlparse(url)
        base = urlparse(base_url)
    except ValueError:
        return False
    if (current.hostname or "").lower() != (base.hostname or "").lower():
        return False
    current_path = ((current.path or "/").rstrip("/") or "/").lower()
    base_path = ((base.path or "/").rstrip("/") or "/").lower()
    if current_path == base_path:
        return True
    host = (base.hostname or "").lower()
    if host == "rewards.bing.com" or host.endswith(".rewards.bing.com"):
        return current_path in REWARDS_HOME_PATHS and base_path in REWARDS_HOME_PATHS
    return False
