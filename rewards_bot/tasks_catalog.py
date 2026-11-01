from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

SUPPORT_BASIC = "basic"
SUPPORT_AI = "ai"
SUPPORT_MANUAL = "manual"


@dataclass(frozen=True, slots=True)
class TaskSpec:
    """界面与基础模式共用的任务类型定义。"""

    id: str
    group: str
    label: str
    description: str
    support: str
    default: bool = False
    field: str | None = None
    caution: str | None = None


GROUPS: tuple[dict[str, str], ...] = (
    {
        "id": "daily",
        "label": "每日集锦",
        "hint": "每天刷新，是基础模式最主要的积分来源。",
    },
    {
        "id": "weekly",
        "label": "每周与每月",
        "hint": "周期更长的集锦或打卡，打开卡片后由同一套规则处理。",
    },
    {
        "id": "more",
        "label": "更多活动",
        "hint": "积分较高的测验、投票、阅读与限时活动。",
    },
    {
        "id": "actions",
        "label": "搜索与领取",
        "hint": "不产生任务卡片，但决定是否执行对应动作。",
    },
    {
        "id": "special",
        "label": "特殊与账户任务",
        "hint": "需要进阶 AI、手机/主机或人工判断，不能被基础模式勾选。",
    },
)

TASK_SPECS: tuple[TaskSpec, ...] = (
    TaskSpec(
        "daily_quiz",
        "daily",
        "每日测验",
        "每日集锦中的 quiz / 问答卡片，自动选择选项并推进。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "daily_poll",
        "daily",
        "每日投票",
        "每日集锦中的 poll / 投票卡片，自动完成投票。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "daily_link",
        "daily",
        "每日浏览与阅读",
        "打开链接后停留、滚动并返回，适合浏览/阅读类卡片。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "checkin",
        "daily",
        "每日签到 / 打卡",
        "识别签到、check-in 一类卡片，并按浏览任务停留。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "this_or_that",
        "daily",
        "二选一互动",
        "This or That 等点选小互动，基础引擎选择第一个可用选项。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "weekly_set",
        "weekly",
        "每周集锦",
        "每周任务集合；点开后若出现测验/投票，会继续按基础规则处理。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "monthly_set",
        "weekly",
        "每月集锦 / 月度打卡",
        "月度任务或打卡集合，处理方式与每周集锦一致。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "more_quiz",
        "more",
        "更多活动 · 测验",
        "更多活动中的知识问答，通常积分高于每日测验。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "more_poll",
        "more",
        "更多活动 · 投票",
        "更多活动中的投票/选择类任务。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "more_link",
        "more",
        "更多活动 · 浏览阅读",
        "打开并停留，适合普通链接、文章和探索卡片。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "video",
        "more",
        "视频观看类",
        "识别视频/观看卡片，打开页面后等待并滚动。",
        SUPPORT_BASIC,
        default=True,
    ),
    TaskSpec(
        "promo_card",
        "more",
        "推广 / 限时活动卡片",
        "文案和步骤不固定，需要 AI 结合页面元素实时判断。",
        SUPPORT_AI,
    ),
    TaskSpec(
        "survey",
        "more",
        "问卷与调查",
        "答案取决于真实情况与上下文，必须由进阶 AI 或人工处理。",
        SUPPORT_AI,
    ),
    TaskSpec(
        "web_search",
        "actions",
        "Bing 每日搜索",
        "用随机词完成网页搜索次数；更容易触发风控，默认关闭。",
        SUPPORT_BASIC,
        default=False,
        field="search_enabled",
        caution="高频自动搜索可能被 Microsoft 判定为异常流量，收益也不稳定。",
    ),
    TaskSpec(
        "claim",
        "actions",
        "领取已完成的奖励",
        "只点击明确的「领取 / Claim」，绝不点击「兑换 / Redeem」。",
        SUPPORT_BASIC,
        default=True,
        field="auto_claim",
    ),
    TaskSpec(
        "special_events",
        "special",
        "特殊限时活动",
        "多步骤、动态文案或需要探索的限时活动，基础规则无法可靠识别。",
        SUPPORT_AI,
    ),
    TaskSpec(
        "streak",
        "special",
        "连胜 / 连续记录保护",
        "连续记录本身通常自动统计；出现保护或恢复任务时需 AI 判断。",
        SUPPORT_AI,
    ),
    TaskSpec(
        "mobile_search",
        "special",
        "移动端搜索",
        "需要使用 Bing 手机 App 或移动设备，桌面基础/进阶模式均不模拟设备。",
        SUPPORT_MANUAL,
    ),
    TaskSpec(
        "xbox",
        "special",
        "Xbox / Game Pass 任务",
        "通常需要已关联主机、完成启动游戏或购买内容，无法在网页内自动完成。",
        SUPPORT_MANUAL,
    ),
    TaskSpec(
        "mobile_app",
        "special",
        "Rewards App 专属任务",
        "仅在 Microsoft Rewards 手机 App 中出现，桌面程序不处理。",
        SUPPORT_MANUAL,
    ),
    TaskSpec(
        "purchase",
        "special",
        "购买 / 购物返积分",
        "涉及真实支付与订单确认，程序永远不会自动购买或填写支付信息。",
        SUPPORT_MANUAL,
    ),
    TaskSpec(
        "referral",
        "special",
        "邀请好友",
        "需要真实联系人参与，无法自动完成，也不适合自动骚扰他人。",
        SUPPORT_MANUAL,
    ),
    TaskSpec(
        "profile",
        "special",
        "完善资料 / 账户任务",
        "涉及个人资料与账户安全，留给你手动确认。",
        SUPPORT_MANUAL,
    ),
)

TASK_BY_ID: dict[str, TaskSpec] = {spec.id: spec for spec in TASK_SPECS}
TASK_IDS: tuple[str, ...] = tuple(spec.id for spec in TASK_SPECS)
BASIC_CARD_TASK_IDS: tuple[str, ...] = tuple(
    spec.id
    for spec in TASK_SPECS
    if spec.support == SUPPORT_BASIC and spec.field is None
)
DEFAULT_TASK_TYPES: tuple[str, ...] = tuple(
    spec.id for spec in TASK_SPECS if spec.id in BASIC_CARD_TASK_IDS and spec.default
)
AI_ONLY_TASK_IDS: tuple[str, ...] = tuple(
    spec.id for spec in TASK_SPECS if spec.support == SUPPORT_AI
)
MANUAL_TASK_IDS: tuple[str, ...] = tuple(
    spec.id for spec in TASK_SPECS if spec.support == SUPPORT_MANUAL
)

# 本地预估用的保守积分区间，不代表 Microsoft 官方数值。
# 实际积分会随地区、账号、活动文案和当天页面的任务数量变化。
# (最低, 最高, 周期)
POINT_ESTIMATES: dict[str, tuple[int, int, str]] = {
    "daily_quiz": (10, 50, "daily"),
    "daily_poll": (5, 20, "daily"),
    "daily_link": (5, 20, "daily"),
    "checkin": (5, 20, "daily"),
    "this_or_that": (5, 20, "daily"),
    "weekly_set": (50, 150, "weekly"),
    "monthly_set": (100, 500, "monthly"),
    "more_quiz": (10, 50, "daily"),
    "more_poll": (5, 20, "daily"),
    "more_link": (5, 20, "daily"),
    "video": (5, 20, "daily"),
    "web_search": (0, 90, "daily"),
}

_MANUAL_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (
        re.compile(
            r"购买|購買|购物|購物|返利|订单|訂單|purchase|buy now|shopping|"
            r"checkout|payment|支付"
        ),
        "purchase",
    ),
    (
        re.compile(r"xbox|game\s*pass|主机任务|主機任務|主机游戏|console", re.I),
        "xbox",
    ),
    (
        re.compile(r"移动端搜索|移動端搜尋|手机搜索|手機搜尋|mobile\s*search", re.I),
        "mobile_search",
    ),
    (
        re.compile(
            r"移动应用专属|移動應用專屬|rewards\s*app|bing\s*app|app\s*专属|"
            r"mobile\s*app",
            re.I,
        ),
        "mobile_app",
    ),
    (
        re.compile(r"邀请好友|邀請好友|邀请朋友|推薦好友|推荐好友|referral|refer a friend|invite", re.I),
        "referral",
    ),
    (
        re.compile(r"完善.{0,6}(资料|資料|档案|檔案)|个人资料|個人資料|profile|账户信息|帳戶資訊", re.I),
        "profile",
    ),
)

_AI_RULES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"问卷|問卷|调查|調查|反馈|反饋|survey|feedback", re.I), "survey"),
    (
        re.compile(
            r"连胜|連勝|连签|連簽|连续记录|連續記錄|streak|连续打卡保护", re.I
        ),
        "streak",
    ),
    (
        re.compile(
            r"限时活动|限時活動|专属活动|專屬活動|促销活动|促銷活動|"
            r"special\s*event|limited[-\s]*time|promotion",
            re.I,
        ),
        "special_events",
    ),
)

_CHECKIN_RE = re.compile(r"签到|簽到|打卡|check[-\s]*in", re.I)
_THIS_OR_THAT_RE = re.compile(r"this\s+or\s+that|二选一|二選一|哪个更|哪個更", re.I)
_QUIZ_RE = re.compile(r"测验|測驗|\bquiz\b|问答|問答|答题|答題|知识挑战|知識挑戰", re.I)
_POLL_RE = re.compile(r"投票|poll|vote|选择|選擇", re.I)
_VIDEO_RE = re.compile(r"视频|影片|video|watch|观看|觀看", re.I)


def _normalize_section(section: Any) -> str:
    value = str(section or "").strip().lower()
    if value in {"daily", "more", "weekly", "monthly"}:
        return value
    return "unknown"


def _haystack(task: dict[str, Any]) -> str:
    parts = [
        str(task.get("text") or ""),
        str(task.get("own_text") or ""),
        str(task.get("href") or ""),
    ]
    return " " + " ".join(parts) + " "


def classify_task(task: dict[str, Any]) -> str:
    """把仪表盘卡片归入任务目录，供基础模式决定是否处理。

    规则只用于筛选页面卡片，不确定时落到“浏览/阅读”类，
    保持基础模式原有的打开页面并停留能力。
    """

    text = _haystack(task)
    section = _normalize_section(task.get("section"))

    for pattern, task_id in _MANUAL_RULES:
        if pattern.search(text):
            return task_id
    for pattern, task_id in _AI_RULES:
        if pattern.search(text):
            return task_id

    if section == "weekly":
        return "weekly_set"
    if section == "monthly":
        return "monthly_set"

    if _CHECKIN_RE.search(text):
        return "checkin"
    if _THIS_OR_THAT_RE.search(text):
        return "this_or_that"
    if _QUIZ_RE.search(text):
        return "more_quiz" if section != "daily" else "daily_quiz"
    if _POLL_RE.search(text):
        return "more_poll" if section != "daily" else "daily_poll"
    if _VIDEO_RE.search(text):
        return "video"
    if section == "daily":
        return "daily_link"
    return "more_link"


def validate_task_types(value: Any) -> list[str]:
    """校验界面提交的任务类型，返回按目录顺序排列的列表。"""

    if not isinstance(value, (list, tuple)):
        raise ValueError("basic.task_types 必须是字符串数组。")
    selected: set[str] = set()
    for item in value:
        if not isinstance(item, str):
            raise ValueError("basic.task_types 只能包含字符串。")
        task_id = item.strip()
        if not task_id:
            continue
        spec = TASK_BY_ID.get(task_id)
        if spec is None:
            raise ValueError(f"未知任务类型：{task_id}")
        if task_id not in BASIC_CARD_TASK_IDS:
            raise ValueError(f"任务「{spec.label}」不能通过基础任务清单启用。")
        selected.add(task_id)
    return [task_id for task_id in BASIC_CARD_TASK_IDS if task_id in selected]


def catalog_payload() -> dict[str, Any]:
    items = []
    for spec in TASK_SPECS:
        items.append(
            {
                "id": spec.id,
                "group": spec.group,
                "label": spec.label,
                "description": spec.description,
                "support": spec.support,
                "default": spec.default,
                "field": spec.field,
                "caution": spec.caution,
            }
        )
    return {
        "groups": list(GROUPS),
        "items": items,
        "default_task_types": list(DEFAULT_TASK_TYPES),
        "basic_card_task_ids": list(BASIC_CARD_TASK_IDS),
        "support_labels": {
            SUPPORT_BASIC: "内置可完成",
            SUPPORT_AI: "仅进阶 AI",
            SUPPORT_MANUAL: "需人工处理",
        },
    }


def selected_basic_cards(task_types: Iterable[str]) -> set[str]:
    selected = set(task_types)
    return {task_id for task_id in BASIC_CARD_TASK_IDS if task_id in selected}


def _points_range(low: float, high: float) -> dict[str, int]:
    low_value = max(0, int(round(low)))
    high_value = max(low_value, int(round(high)))
    return {
        "low": low_value,
        "high": high_value,
        "mid": int(round((low_value + high_value) / 2)),
    }


def _estimate_totals(
    task_ids: Iterable[str],
    *,
    search_enabled: bool,
    search_count: int,
) -> tuple[dict[str, int], dict[str, int]]:
    """按任务类型估算每日/每周积分，周/月任务按周期摊销。"""

    daily_low = daily_high = 0
    weekly_low = weekly_high = 0
    monthly_low = monthly_high = 0
    for task_id in set(task_ids):
        estimate = POINT_ESTIMATES.get(task_id)
        if estimate is None:
            continue
        low, high, cadence = estimate
        if cadence == "weekly":
            weekly_low += low
            weekly_high += high
        elif cadence == "monthly":
            monthly_low += low
            monthly_high += high
        else:
            daily_low += low
            daily_high += high

    if search_enabled:
        # 桌面搜索通常按次数给分，这里按每次 3 分、最多 30 次封顶。
        searches = max(0, min(int(search_count or 0), 30))
        daily_high += min(searches * 3, 90)

    day_low = daily_low + weekly_low / 7 + monthly_low / 30
    day_high = daily_high + weekly_high / 7 + monthly_high / 30
    week_low = daily_low * 7 + weekly_low + monthly_low * 7 / 30
    week_high = daily_high * 7 + weekly_high + monthly_high * 7 / 30
    return _points_range(day_low, day_high), _points_range(week_low, week_high)


def points_forecast(
    task_types: Iterable[str],
    *,
    search_enabled: bool = False,
    search_count: int = 0,
    auto_claim: bool = True,
) -> dict[str, Any]:
    """生成首页使用的积分预估与未启用项。

    这只是按任务类型给出的本地估算，不读取账号余额，也不代表
    Microsoft 的官方积分；实际以 Rewards 页面为准。
    """

    selected = selected_basic_cards(task_types)
    missing_cards = [task_id for task_id in BASIC_CARD_TASK_IDS if task_id not in selected]
    missing_ids = list(missing_cards)
    if not search_enabled:
        missing_ids.append("web_search")

    daily, weekly = _estimate_totals(
        selected,
        search_enabled=search_enabled,
        search_count=search_count,
    )
    missing_daily, missing_weekly = _estimate_totals(
        missing_cards,
        search_enabled=not search_enabled,
        search_count=search_count,
    )
    return {
        "estimated": True,
        "daily": daily,
        "weekly": weekly,
        "selected_count": len(selected),
        "selectable_count": len(BASIC_CARD_TASK_IDS),
        "missing_ids": missing_ids,
        "missing_labels": [
            TASK_BY_ID[task_id].label for task_id in missing_ids if task_id in TASK_BY_ID
        ],
        "missing_count": len(missing_ids),
        "missing_daily": missing_daily,
        "missing_weekly": missing_weekly,
        "search_enabled": bool(search_enabled),
        "search_count": max(0, min(int(search_count or 0), 100)),
        "auto_claim": bool(auto_claim),
        "locked_ai_count": len(AI_ONLY_TASK_IDS),
        "locked_manual_count": len(MANUAL_TASK_IDS),
    }
