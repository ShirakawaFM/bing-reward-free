from __future__ import annotations

import logging
import random
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from playwright.sync_api import Error as PlaywrightError

from .browser import BrowserSession, LoginRequired
from .config import AppConfig
from .dom import host_allowed, is_rewards_home_url

if TYPE_CHECKING:
    from .points import PointsTracker
from .tasks_catalog import (
    SUPPORT_BASIC,
    TASK_BY_ID,
    classify_task,
    selected_basic_cards,
)

BASIC_ALLOWED_HOSTS = ["bing.com", "rewards.bing.com"]

SCAN_TASKS_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-qbot-task]').forEach((el) => el.removeAttribute('data-qbot-task'));
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 8 || rect.height < 8) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const isDone = (text) => /(已完成|已领取|已完成任务|completed|claimed)/i.test(text || '');
  const isRisky = (text, href) => /(兑换|兌換|redeem|购买|購買|shop|catalog|设置|設定|privacy)/i.test((text || '') + ' ' + (href || ''));
  const isLearnMore = (text) => /^(了解更多|查看详情|learn more|more info|terms|条款|隐私|privacy)$/i.test(norm(text));
  const pointsRe = /(?:[+＋]\s*\d{1,4}\b)|(?:\d{1,4}\s*(?:积分|積分|points?|pts?))/i;
  const taskRe = /(quiz|poll|测验|測驗|投票|问答|問答|this or that|每日任务|daily task|打卡)/i;

  const sectionOf = (el) => {
    const sectionEl = el.closest(
      'mee-rewards-daily-set-section, mee-rewards-more-activities-section, ' +
      '[class*="daily" i], [id*="daily" i], [class*="weekly" i], [id*="weekly" i], ' +
      '[class*="monthly" i], [id*="monthly" i], [class*="more-activit" i], ' +
      '[class*="moreActivit" i], [class*="activity" i], [class*="task" i]'
    );
    if (!sectionEl) return 'unknown';
    let signature = '';
    try {
      signature = (
        (sectionEl.id || '') + ' ' +
        (typeof sectionEl.className === 'string' ? sectionEl.className : '') + ' ' +
        (sectionEl.tagName || '')
      ).toLowerCase();
    } catch (err) {
      return 'unknown';
    }
    if (/month|月度|每月|monthly/.test(signature)) return 'monthly';
    if (/week|每周|每週|weekly/.test(signature)) return 'weekly';
    if (/daily|每日/.test(signature)) return 'daily';
    if (/more|更多/.test(signature)) return 'more';
    if (/activit|活动|活動|task|任务|任務/.test(signature)) return 'more';
    return 'unknown';
  };

  const anchors = Array.from(
    document.querySelectorAll(
      'mee-card a[href], [class*="card" i] a[href], a[href]'
    )
  );
  const raw = [];
  const seen = new Set();

  for (const el of anchors) {
    if (!visible(el)) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    if (el.closest('header, nav, footer, [role="navigation"], [role="banner"], [role="contentinfo"]')) continue;

    const ownText = norm(el.innerText || el.getAttribute('aria-label') || '');
    if (isLearnMore(ownText)) continue;
    const card = el.closest('mee-card, [class*="card" i], li, article') || el;
    let text = norm(card.innerText || '');
    if (!text) text = ownText;
    if (!text || text.length > 420) continue;
    if (isDone(text)) continue;

    const href = typeof el.href === 'string' ? el.href : '';
    if (!href) continue;
    if (isRisky(text, href)) continue;
    if (href && /(login\.live\.com|login\.microsoftonline\.com|login\.windows\.net)/i.test(href)) continue;

    const hasPoints = pointsRe.test(text) || pointsRe.test(ownText);
    const hasTaskWord = taskRe.test(text) || taskRe.test(ownText);
    if (!hasPoints && !hasTaskWord) continue;

    const inKnownSection = !!el.closest(
      'mee-rewards-daily-set-section, mee-rewards-more-activities-section, ' +
      '[class*="daily" i], [id*="daily" i], [class*="activity" i], [class*="task" i]'
    );
    const rect = el.getBoundingClientRect();
    const score = (inKnownSection ? 10 : 0)
      + (ownText === text ? 4 : 0)
      + (taskRe.test(ownText) ? 3 : 0)
      + Math.min(4, Math.round((rect.width * rect.height) / 40000));
    let key;
    try {
      key = href && !href.startsWith('javascript:') ? href : text.slice(0, 140) + '|' + ownText.slice(0, 80);
    } catch (err) {
      key = text.slice(0, 140);
    }
    if (seen.has(key)) continue;
    seen.add(key);
    raw.push({ el: el, text: text.slice(0, 240), ownText: ownText.slice(0, 160), href: href, score: score, top: Math.round(rect.top + window.scrollY), section: sectionOf(el) });
  }

  raw.sort((a, b) => (b.score - a.score) || (a.top - b.top));
  const out = [];
  for (const item of raw.slice(0, 20)) {
    const idx = out.length;
    item.el.setAttribute('data-qbot-task', String(idx));
    out.push({ idx: idx, text: item.text, own_text: item.ownText, href: item.href, section: item.section });
  }
  return out;
}
"""

MARK_ANSWER_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-qbot-answer]').forEach((el) => el.removeAttribute('data-qbot-answer'));
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const progressRe = /^(下一页|下一题|继续|提交|提交答案|投票|完成|完成测验|查看结果|next|next question|continue|submit|submit answer|vote|finish|done|see results|claim)$/i;
  const badRe = /(登录|sign in|退出|sign out|兑换|redeem|返回|back|关闭|close|取消|cancel)/i;

  const chooseTarget = (el) => {
    if (!el) return null;
    if (el.tagName === 'INPUT') {
      if (visible(el)) return el;
      try {
        const id = el.id;
        const label = el.closest('label') || (id ? document.querySelector('label[for="' + CSS.escape(id) + '"]') : null);
        if (label && visible(label)) return label;
      } catch (err) {}
      return null;
    }
    return el;
  };
  const usable = (el) => {
    if (!el) return false;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') return false;
    let text = norm(el.innerText || el.getAttribute('aria-label') || el.value || '');
    text = text.replace(/^[>›»→\s]+|[<‹«←\s]+$/g, '');
    if (!text || text.length > 240) return false;
    if (progressRe.test(text) || badRe.test(text)) return false;
    if (el.closest('header, nav, footer, [role="banner"], [role="contentinfo"]')) return false;
    return true;
  };

  const selectors = [
    '#rOption0', '#rOption1', '#rOption2', '#rOption3',
    '[id^="rOption"]',
    'input[type="radio"]:not(:checked)',
    '[role="radio"][aria-checked="false"]',
    '[role="option"][aria-selected="false"]',
    '.wk_Option:not(.wk_OptionSelected)',
    '[class*="answerOption" i]',
    '[class*="quizOption" i]',
    '[class*="optionButton" i]',
    '[class*="choice" i] a',
    '[class*="option" i] a'
  ];
  for (const selector of selectors) {
    let nodes = [];
    try {
      nodes = Array.from(document.querySelectorAll(selector));
    } catch (err) {
      continue;
    }
    for (const node of nodes) {
      const target = chooseTarget(node);
      if (!target || !visible(target) || !usable(target)) continue;
      const href = typeof target.href === 'string' ? target.href : '';
      if (href && /^https?:/i.test(href)) {
        let host = '';
        try { host = new URL(href).hostname; } catch (err) {}
        if (host && host !== 'bing.com' && !host.endsWith('.bing.com') && host !== 'rewards.bing.com' && !host.endsWith('.rewards.bing.com')) {
          continue;
        }
      }
      if (href && /redeem|兑换|shop|catalog/i.test(href)) continue;
      target.setAttribute('data-qbot-answer', '1');
      return norm(target.innerText || target.getAttribute('aria-label') || target.value || '答案选项');
    }
  }

  // 仅当页面明显离开任务列表页、且存在测验容器时，做最后兜底。
  if (/\/(dashboard|earn)$/i.test(location.pathname.replace(/\/+$/, ''))) return '';

  const pageText = norm(document.body ? document.body.innerText.slice(0, 8000) : '');
  if (!/(quiz|测验|測驗|问答|問答|投票|poll|this or that)/i.test(pageText)) return '';
  let quizRoot = null;
  for (const rootSelector of [
    '[class*="quiz" i]', '[id*="quiz" i]', '[class*="poll" i]',
    '[class*="question" i]', '[class*="activity" i]'
  ]) {
    try {
      quizRoot = document.querySelector(rootSelector);
    } catch (err) {
      quizRoot = null;
    }
    if (quizRoot) break;
  }
  if (!quizRoot) return '';
  const options = Array.from(quizRoot.querySelectorAll('button, a, [role="radio"], [role="option"]'))
    .filter((el) => visible(el) && usable(el))
    .filter((el) => {
      const text = norm(el.innerText || el.getAttribute('aria-label') || '');
      return text.length >= 2 && text.length <= 120;
    });
  if (options.length < 2 || options.length > 10) return '';
  const target = options[0];
  target.setAttribute('data-qbot-answer', '1');
  return norm(target.innerText || target.getAttribute('aria-label') || '答案选项');
}
"""

MARK_PROGRESS_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-qbot-progress]').forEach((el) => el.removeAttribute('data-qbot-progress'));
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const labels = [
    '下一页', '下一题', '下一个', '继续', '提交', '提交答案', '投票',
    '完成', '完成测验', '查看结果', '领取', '领取奖励',
    'next', 'next question', 'continue', 'submit', 'submit answer',
    'vote', 'finish', 'done', 'see results', 'claim', 'claim points', 'claim reward'
  ];
  const banned = /^(取消|cancel|关闭|close|返回|back|退出|sign out|登录|sign in)$/i;
  const nodes = Array.from(document.querySelectorAll(
    'button, a, [role="button"], input[type="submit"], input[type="button"], ' +
    '[id*="next" i], [class*="next" i]'
  ));
  for (const el of nodes) {
    if (!visible(el)) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    if (el.closest('header, nav, footer, [role="banner"], [role="contentinfo"]')) continue;
    // 不要把 Bing 搜索结果的分页当成测验的“下一页”。
    if (el.closest('#b_results, .b_pag, .b_content, [class*="pagination" i], [class*="paginator" i]')) continue;
    const cls = (el.className || '').toString();
    if (/pag|pagination|paginator/i.test(cls)) continue;
    const href = typeof el.href === 'string' ? el.href : '';
    if (/[?&]first=\d+/i.test(href)) continue;
    let text = norm(el.innerText || el.value || el.getAttribute('aria-label') || '');
    text = text.replace(/^[>›»→\s]+|[<‹«←\s]+$/g, '');
    if (!text || text.length > 40 || banned.test(text)) continue;
    const lower = text.toLowerCase();
    const matches = labels.some((label) => {
      const needle = label.toLowerCase();
      return lower === needle
        || lower.startsWith(needle + ' ')
        || lower.startsWith(needle + '（')
        || lower.startsWith(needle + '(');
    });
    if (!matches) continue;
    if (href && /(redeem|兑换|shop|catalog|login\.live|login\.microsoft)/i.test(href)) continue;
    el.setAttribute('data-qbot-progress', '1');
    return norm(el.innerText || el.value || el.getAttribute('aria-label') || text);
  }
  return '';
}
"""

QUIZ_DETECT_JS = r"""
() => {
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const radios = Array.from(document.querySelectorAll('input[type="radio"]')).filter(visible);
  if (radios.length >= 2) return true;
  if (Array.from(document.querySelectorAll('[role="radio"]')).filter(visible).length >= 2) return true;
  for (const group of document.querySelectorAll('[role="radiogroup"]')) {
    if (group.querySelectorAll('[role="radio"]').length >= 2) return true;
  }
  for (const selector of [
    '#rOption0', '[id^="rOption"]', '.wk_Option',
    '[class*="quizOption" i]', '[class*="answerOption" i]', '[class*="optionButton" i]'
  ]) {
    try {
      if (Array.from(document.querySelectorAll(selector)).some(visible)) return true;
    } catch (err) {}
  }
  const dialog = document.querySelector('[role="dialog"], dialog[open], [aria-modal="true"]');
  if (dialog && visible(dialog)) {
    const text = (dialog.innerText || '').slice(0, 3000);
    const options = Array.from(dialog.querySelectorAll('button, a, [role="radio"], [role="option"]'))
      .filter((el) => visible(el) && !el.disabled);
    if (options.length >= 2 && /(quiz|测验|測驗|问答|問答|投票|poll|this or that)/i.test(text)) {
      return true;
    }
  }
  return false;
}
"""

MARK_CLAIMS_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  document.querySelectorAll('[data-qbot-claim]').forEach((el) => el.removeAttribute('data-qbot-claim'));
  const visible = (el) => {
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const claimRe = /^(领取|领取奖励|领取积分|领取奖励积分|claim|claim points|claim reward|claim rewards|claim now|可领取.*领取)$/i;
  const nodes = Array.from(document.querySelectorAll('button, a, [role="button"]'));
  const out = [];
  for (const el of nodes) {
    if (!visible(el)) continue;
    if (el.disabled || el.getAttribute('aria-disabled') === 'true') continue;
    let text = norm(el.innerText || el.getAttribute('aria-label') || '');
    text = text.replace(/^[>›»→\s]+|[<‹«←\s]+$/g, '');
    if (!claimRe.test(text) || /(兑换|redeem)/i.test(text)) continue;
    const href = typeof el.href === 'string' ? el.href : '';
    if (href && /(redeem|兑换|shop|catalog)/i.test(href)) continue;
    const idx = out.length;
    el.setAttribute('data-qbot-claim', String(idx));
    out.push({ idx: idx, text: text });
    if (out.length >= 6) break;
  }
  return out;
}
"""

MARK_CLAIM_CONFIRM_JS = r"""
() => {
  const norm = (value) => (value || '').replace(/\s+/g, ' ').trim();
  const visible = (el) => {
    if (!el) return false;
    const rect = el.getBoundingClientRect();
    if (rect.width < 5 || rect.height < 5) return false;
    const style = getComputedStyle(el);
    return style.visibility !== 'hidden' && style.display !== 'none' && Number(style.opacity || '1') > 0.05;
  };
  const root = document.querySelector('[role="dialog"], dialog[open], [aria-modal="true"], .modal');
  if (!root) return '';
  const allowed = /^(领取|确认领取|确定|确认|好的|继续|ok|okay|claim|continue)$/i;
  const banned = /(取消|关闭|cancel|close|兑换|redeem|兑换奖励)/i;
  for (const el of root.querySelectorAll('button, a, [role="button"]')) {
    if (!visible(el)) continue;
    const text = norm(el.innerText || el.getAttribute('aria-label') || '');
    if (!text || text.length > 30 || banned.test(text)) continue;
    if (!allowed.test(text)) continue;
    el.setAttribute('data-qbot-confirm', '1');
    return text;
  }
  return '';
}
"""

DEFAULT_QUERIES = [
    "今天有什么新闻",
    "Windows 使用技巧",
    "人工智能 最新进展",
    "如何提高工作效率",
    "本周天气",
    "健康饮食 建议",
    "旅行 攻略",
    "Python 入门教程",
    "适合周末看的电影",
    "新能源汽车 对比",
    "咖啡 怎么冲泡",
    "居家健身 方法",
    "摄影 入门",
    "读书 推荐",
    "历史 故事",
    "Excel 函数 技巧",
    "城市 美食",
    "科技 新闻",
    "环保 生活",
    "音乐 推荐",
]


class BasicRunner:
    """不使用大模型的基础自动化：卡片扫描 + 通用答题 + 领取。"""

    def __init__(
        self,
        session: BrowserSession,
        cfg: AppConfig,
        points: "PointsTracker | None" = None,
    ) -> None:
        self.session = session
        self.cfg = cfg
        self.points = points
        self.log = logging.getLogger("rewards_bot.basic")
        self.dashboard_url = cfg.general.url
        self.random = random.Random()

    # ---------- 公共 ----------

    def _ensure_dashboard(self):
        page = self.session.current_page
        if is_rewards_home_url(page.url, self.dashboard_url) and not self.session.is_login_page():
            return page
        page = self.session.open_dashboard()
        return page

    @staticmethod
    def _task_key(task: dict) -> str:
        href = (task.get("href") or "").strip()
        if href and not href.startswith("javascript:"):
            return href
        return f"{(task.get('text') or '')[:160]}|{(task.get('own_text') or '')[:80]}"

    def _click_marked(self, attribute: str, timeout: int = 7_000) -> str | None:
        page = self.session.current_page
        locator = page.locator(f'[{attribute}="1"]').first
        try:
            if page.locator(f'[{attribute}="1"]').count() == 0:
                return None
            info = locator.evaluate(
                """(el) => ({
                    text: ((el.innerText || el.getAttribute('aria-label') || el.value || '') + '')
                      .replace(/\\s+/g, ' ').trim().slice(0, 200),
                    href: typeof el.href === 'string' ? el.href : ''
                })"""
            )
            href = str(info.get("href") or "")
            if href:
                host = (urlparse(href).hostname or "").lower()
                if host and not host_allowed(host, BASIC_ALLOWED_HOSTS):
                    self.log.debug("跳过站外链接：%s", href[:160])
                    locator.evaluate("(el) => el.removeAttribute('" + attribute + "')")
                    return None
            label = str(info.get("text") or "").strip()
            try:
                locator.scroll_into_view_if_needed(timeout=3_000)
            except PlaywrightError:
                pass
            locator.click(timeout=timeout)
            page.wait_for_timeout(900)
            self.session.adopt_new_pages()
            try:
                self.session.current_page.wait_for_load_state("domcontentloaded", timeout=6_000)
            except Exception:
                pass
            self.session.current_page.wait_for_timeout(500)
            return label or "（无文字元素）"
        except PlaywrightError as exc:
            self.log.debug("点击标记元素失败：%s", str(exc).splitlines()[0][:180])
            try:
                locator.evaluate("(el) => el.removeAttribute('" + attribute + "')")
            except Exception:
                pass
            return None

    def _pause(self, page, low_ms: int, high_ms: int) -> None:
        """按防检测设置等待：开启时用右偏分布（每次不同），关闭时保持均匀随机。"""
        low = max(0.01, low_ms / 1000.0)
        high = max(low, high_ms / 1000.0)
        if self.cfg.stealth.enabled:
            from .stealth import sample_span

            seconds = sample_span(self.random, low, high)
        else:
            seconds = self.random.uniform(low, high)
        try:
            page.wait_for_timeout(max(1, int(seconds * 1000)))
        except PlaywrightError:
            pass

    def _human_click(self, locator) -> None:
        """先把鼠标挪到目标上再点，而不是直接触发 click。"""
        if self.cfg.stealth.mouse_jitter:
            page = self.session.current_page
            try:
                box = locator.bounding_box()
                if box:
                    page.mouse.move(
                        box["x"] + box["width"] * self.random.uniform(0.25, 0.75),
                        box["y"] + box["height"] * self.random.uniform(0.3, 0.7),
                        steps=self.random.randint(8, 22),
                    )
                    self._pause(page, 60, 280)
            except PlaywrightError:
                pass
        self.session.click_maybe_popup(locator)

    def _page_state(self) -> str:
        try:
            return self.session.current_page.evaluate(
                """() => {
                    const main = document.querySelector('main, [role="main"]') || document.body;
                    return location.href + '|' + ((main && main.innerText) || '').slice(0, 1200);
                }"""
            )
        except Exception:
            return ""

    # ---------- 每日任务 ----------

    def run_daily_tasks(self) -> int:
        attempted: set[str] = set()
        processed = 0
        max_tasks = self.cfg.basic.max_tasks
        selected = selected_basic_cards(self.cfg.basic.task_types)
        reported_skips: set[str] = set()
        if not selected:
            self.log.warning("基础任务清单为空，本轮不会处理任务卡片。")

        # 积分证据要求每完成一个任务后重新读取汇率；若因此刷新了页面，
        # 当前扫描里的 data-qbot-task 标记会失效，需要回到外层重新扫描。
        max_scans = max(6, max_tasks * 3)
        for scan in range(max_scans):
            if processed >= max_tasks:
                break
            page = self._ensure_dashboard()
            try:
                tasks = page.evaluate(SCAN_TASKS_JS)
            except PlaywrightError as exc:
                self.log.warning("扫描任务卡片失败：%s", exc)
                break
            tasks = tasks if isinstance(tasks, list) else []
            new_tasks = []
            skipped: dict[str, int] = {}
            for task in tasks:
                if self._task_key(task) in attempted:
                    continue
                category = classify_task(task)
                spec = TASK_BY_ID.get(category)
                if (
                    category in selected
                    and spec is not None
                    and spec.support == SUPPORT_BASIC
                    and spec.field is None
                ):
                    new_tasks.append(task)
                    continue
                skipped[category] = skipped.get(category, 0) + 1
                if category not in reported_skips:
                    reported_skips.add(category)
                    label = spec.label if spec else "未知任务"
                    reason = (
                        "未勾选"
                        if spec is not None and spec.support == SUPPORT_BASIC
                        else "需要进阶 AI"
                        if spec is not None and spec.support == "ai"
                        else "需要人工处理"
                        if spec is not None
                        else "无法归类"
                    )
                    self.log.info("跳过任务类型「%s」（%s）：%s", label, reason, str(task.get("text") or "")[:100])
            self.log.info(
                "第 %s 轮扫描：候选任务 %s 个，可处理 %s 个，跳过 %s 个",
                scan + 1,
                len(tasks),
                len(new_tasks),
                sum(skipped.values()),
            )
            if not new_tasks:
                break

            processed_this_scan = 0
            reloaded = False
            for task in new_tasks:
                if processed >= max_tasks:
                    break
                key = self._task_key(task)
                if key in attempted:
                    continue
                attempted.add(key)
                processed += 1
                processed_this_scan += 1
                label = str(task.get("text") or "")[:150]
                self.log.info("处理任务 %s/%s：%s", processed, max_tasks, label)
                dashboard_failed = False
                login_lost = False
                evidence = None
                clicked = False
                try:
                    page = self.session.current_page
                    locator = page.locator(f'[data-qbot-task="{task["idx"]}"]').first
                    if page.locator(f'[data-qbot-task="{task["idx"]}"]').count() == 0:
                        self.log.warning("任务元素已消失，跳过。")
                    else:
                        if self.points is not None:
                            evidence = self.points.before_task(processed, label)
                        try:
                            locator.scroll_into_view_if_needed(timeout=3_000)
                        except PlaywrightError:
                            pass
                        self._human_click(locator)
                        clicked = True
                        self._handle_task_page(label)
                except LoginRequired:
                    login_lost = True
                    raise
                except Exception as exc:
                    self.log.warning("处理任务失败：%s", str(exc).splitlines()[0][:220])
                    self.session.screenshot(f"task-error-{processed}")
                finally:
                    try:
                        self._ensure_dashboard()
                    except LoginRequired:
                        raise
                    except Exception as exc:
                        self.log.warning("返回任务页失败：%s", exc)
                        # 无法回到任务页时结束本轮任务，避免继续在未知页面点击。
                        dashboard_failed = True
                    if self.points is not None and evidence is not None:
                        if clicked and not login_lost and not dashboard_failed:
                            result = self.points.finish_task(evidence)
                            if result.get("page_reloaded"):
                                reloaded = True
                        else:
                            self.points.cancel_task(
                                evidence,
                                "登录失效" if login_lost else "未完成任务或无法返回任务页",
                            )
                if dashboard_failed:
                    return processed
                if reloaded:
                    break
            if processed_this_scan == 0:
                break
            if reloaded:
                continue

        self.log.info("基础任务处理结束，共尝试 %s 个任务。", processed)
        return processed

    def _handle_task_page(self, label: str) -> None:
        page = self.session.current_page
        if self.session.is_login_page():
            raise LoginRequired("任务页面要求登录，请先运行 --login。")
        host = (urlparse(page.url).hostname or "").lower()
        if host and not host_allowed(host, BASIC_ALLOWED_HOSTS):
            self.log.info("任务跳转到站外页面，基础模式不处理：%s", page.url[:180])
            return
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8_000)
        except Exception:
            pass
        self._pause(page, 1_200, 2_200)

        try:
            quiz_like = bool(page.evaluate(QUIZ_DETECT_JS))
        except PlaywrightError as exc:
            self.log.debug("检测答题界面失败：%s", exc)
            quiz_like = False

        if not quiz_like:
            self.log.info(
                "没有检测到测验/投票控件，按搜索或阅读任务停留 %s 秒后返回。",
                self.cfg.basic.read_wait_seconds,
            )
            try:
                page.mouse.wheel(0, self.random.randint(180, 520))
            except PlaywrightError:
                pass
            self.session.current_page.wait_for_timeout(self.cfg.basic.read_wait_seconds * 1000)
            return

        state = self._page_state()
        same_state = 0
        actions = 0
        for _ in range(self.cfg.basic.max_rounds_per_task):
            if page.is_closed():
                break
            if self.session.is_login_page():
                raise LoginRequired("答题过程中登录失效，请先运行 --login。")

            clicked_answer = self._click_answer(page)
            page = self.session.current_page
            if clicked_answer:
                page.wait_for_timeout(self.random.randint(500, 900))
            page = self.session.current_page
            clicked_progress = self._click_progress(page)
            page = self.session.current_page
            if clicked_answer or clicked_progress:
                actions += 1
                page.wait_for_timeout(self.random.randint(800, 1_400))
            else:
                break

            self.session.adopt_new_pages()
            page = self.session.current_page
            current_host = (urlparse(page.url).hostname or "").lower()
            if current_host and not host_allowed(current_host, BASIC_ALLOWED_HOSTS):
                self.log.info("答题页跳转到站外，停止处理：%s", page.url[:180])
                break
            if self.session.is_login_page():
                raise LoginRequired("答题过程中登录失效，请先运行 --login。")

            new_state = self._page_state()
            if new_state == state:
                same_state += 1
                if same_state >= 3:
                    self.log.debug("页面连续无变化，停止该任务。")
                    break
            else:
                same_state = 0
                state = new_state
            if is_rewards_home_url(page.url, self.dashboard_url):
                break

        if actions == 0:
            self.log.info("未识别到答题控件，按阅读类任务等待 %s 秒。", self.cfg.basic.read_wait_seconds)
            self.session.current_page.wait_for_timeout(self.cfg.basic.read_wait_seconds * 1000)
        self.log.info("任务页处理结束：%s（执行了 %s 次交互）", label[:100], actions)

    def _click_answer(self, page) -> str | None:
        try:
            page.evaluate(MARK_ANSWER_JS)
        except PlaywrightError as exc:
            self.log.debug("标记答案失败：%s", exc)
            return None
        return self._click_marked("data-qbot-answer", timeout=6_000)

    def _click_progress(self, page) -> str | None:
        try:
            page.evaluate(MARK_PROGRESS_JS)
        except PlaywrightError as exc:
            self.log.debug("标记继续按钮失败：%s", exc)
            return None
        return self._click_marked("data-qbot-progress", timeout=6_000)

    # ---------- 领取 ----------

    def claim_rewards(self) -> int:
        claimed = 0
        seen: set[str] = set()
        try:
            page = self._ensure_dashboard()
        except LoginRequired:
            raise
        except Exception as exc:
            self.log.warning("领取奖励前无法打开任务页：%s", exc)
            return 0

        for scan in range(2):
            try:
                page.evaluate(MARK_CLAIMS_JS)
            except PlaywrightError as exc:
                self.log.debug("扫描领取按钮失败：%s", exc)
                break
            locators = page.locator('[data-qbot-claim]')
            count = locators.count()
            if count == 0:
                break
            labels = []
            for i in range(count):
                try:
                    labels.append(locators.nth(i).inner_text(timeout=1_500).strip())
                except Exception:
                    labels.append("")
            clicked_any = False
            for i, label in enumerate(labels):
                if label and label in seen:
                    continue
                if label:
                    seen.add(label)
                locator = page.locator(f'[data-qbot-claim="{i}"]').first
                try:
                    if page.locator(f'[data-qbot-claim="{i}"]').count() == 0:
                        continue
                    self._human_click(locator)
                    claimed += 1
                    clicked_any = True
                    self.log.info("点击领取按钮：%s", label or "(无文字)")
                    page.wait_for_timeout(900)
                    self._confirm_claim_dialog(page)
                except Exception as exc:
                    self.log.warning("点击领取按钮失败：%s", exc)
            if not clicked_any:
                break
            try:
                page = self._ensure_dashboard()
            except Exception:
                break
        if claimed == 0:
            self.log.info("没有发现明确的“领取/Claim”按钮。")
        else:
            self.log.info("共点击 %s 个领取按钮。", claimed)
        return claimed

    def _confirm_claim_dialog(self, page) -> None:
        try:
            label = page.evaluate(MARK_CLAIM_CONFIRM_JS)
        except PlaywrightError:
            return
        if not label:
            return
        try:
            locator = page.locator('[data-qbot-confirm="1"]').first
            if page.locator('[data-qbot-confirm="1"]').count() > 0:
                self._human_click(locator)
                page.wait_for_timeout(700)
                self.log.info("点击领取确认：%s", label)
        except Exception as exc:
            self.log.debug("点击领取确认失败：%s", exc)

    # ---------- 可选：搜索 ----------

    def load_queries(self) -> list[str]:
        path = self.cfg.basic.search_queries_file
        if not path.exists():
            return list(DEFAULT_QUERIES)
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except OSError as exc:
            self.log.warning("读取搜索词文件失败：%s", exc)
            return list(DEFAULT_QUERIES)
        queries = []
        for line in lines:
            text = line.strip()
            if text and not text.startswith("#"):
                queries.append(text)
        return queries or list(DEFAULT_QUERIES)

    def run_searches(self) -> int:
        if not self.cfg.basic.search_enabled:
            return 0
        count = self.cfg.basic.search_count
        if count <= 0:
            return 0
        queries = self.load_queries()
        # 延迟导入：stealth 依赖 config/browser，放在这里避免模块级循环导入。
        from .stealth import build_searcher, describe_modes

        searcher = build_searcher(self.session, self.cfg, log=self.log)
        self.log.info(
            "开始可选搜索任务：%s 次，搜索主机 %s，防检测=%s",
            count,
            self.cfg.basic.search_host,
            describe_modes(self.cfg.stealth),
        )
        self._ensure_dashboard()
        completed = searcher.run(count, queries)
        self.log.info("搜索任务结束：完成 %s/%s 次。", completed, count)
        try:
            self._ensure_dashboard()
        except Exception:
            pass
        return completed
