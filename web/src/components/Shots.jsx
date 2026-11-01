import { useState } from "react";
import { ImageOff } from "lucide-react";
import { withToken } from "../lib/api";
import { formatTime, shotLabel } from "../lib/format";

export function formatRunId(runId) {
  const match = /^(\d{4})(\d{2})(\d{2})-(\d{2})(\d{2})(\d{2})$/.exec(runId || "");
  if (!match) return runId || "运行记录";
  return `${match[1]}.${match[2]}.${match[3]} · ${match[4]}:${match[5]}`;
}

export function ShotThumb({ shot, onOpen, className = "" }) {
  const [failed, setFailed] = useState(false);

  return (
    <button
      type="button"
      className={`shot-thumb ${className}`}
      onClick={() => onOpen?.(shot)}
      aria-label={`查看截图：${shotLabel(shot.name)}`}
    >
      {failed ? (
        <span className="shot-fallback">
          <ImageOff size={22} />
          图片不可用
        </span>
      ) : (
        <img
          src={withToken(shot.url)}
          alt={shotLabel(shot.name)}
          loading="lazy"
          draggable="false"
          onError={() => setFailed(true)}
        />
      )}
      <span className="shot-overlay" />
      <span className="shot-caption">
        <strong>{shotLabel(shot.name)}</strong>
        <small>{formatTime(shot.mtime)}</small>
      </span>
      <span className="shot-open">查看</span>
    </button>
  );
}
