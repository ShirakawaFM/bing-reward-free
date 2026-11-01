import {
  Images,
  LayoutDashboard,
  Settings2,
  Terminal,
} from "lucide-react";

export const NAV_ITEMS = [
  {
    id: "overview",
    label: "总览",
    icon: LayoutDashboard,
    code: "OVERVIEW",
    title: "总览",
    subtitle: "今天的状态，一眼看清。",
  },
  {
    id: "logs",
    label: "实时日志",
    icon: Terminal,
    code: "LIVE LOGS",
    title: "实时日志",
    subtitle: "每一次点击与判断，都有迹可循。",
  },
  {
    id: "gallery",
    label: "运行截图",
    icon: Images,
    code: "EVIDENCE",
    title: "运行现场",
    subtitle: "关键页面的视觉留档，方便排查。",
  },
  {
    id: "settings",
    label: "设置",
    icon: Settings2,
    code: "SETTINGS",
    title: "偏好设置",
    subtitle: "调度、执行与模型，都在这里调校。",
  },
];

export function viewMeta(id) {
  return NAV_ITEMS.find((item) => item.id === id) || NAV_ITEMS[0];
}
