export const TIMEZONES = [
  ["Asia/Shanghai", "中国标准时间 · UTC+8"],
  ["Asia/Hong_Kong", "香港 · UTC+8"],
  ["Asia/Tokyo", "日本 · UTC+9"],
  ["Asia/Singapore", "新加坡 · UTC+8"],
  ["Europe/London", "伦敦 · UTC+0/+1"],
  ["Europe/Berlin", "柏林 · UTC+1/+2"],
  ["America/New_York", "纽约 · UTC-5/-4"],
  ["America/Los_Angeles", "洛杉矶 · UTC-8/-7"],
  ["UTC", "协调世界时 · UTC+0"],
];

export function withCurrentTimezone(timezone) {
  if (!timezone) return TIMEZONES;
  return TIMEZONES.some(([value]) => value === timezone)
    ? TIMEZONES
    : [[timezone, timezone], ...TIMEZONES];
}
