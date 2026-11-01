import { useEffect, useMemo, useState } from "react";
import {
  ChevronLeft,
  ChevronRight,
  Download,
  Images,
  RefreshCw,
} from "lucide-react";
import { Modal, Spinner } from "../components/ui";
import { ShotThumb, formatRunId } from "../components/Shots";
import { withToken } from "../lib/api";
import { formatBytes, formatTime, shotLabel } from "../lib/format";

export default function Gallery({ screenshots, loading, onRefresh }) {
  const [selectedUrl, setSelectedUrl] = useState(null);

  const flat = useMemo(
    () =>
      screenshots.flatMap((group) =>
        group.files.map((file) => ({ ...file, run: group.run })),
      ),
    [screenshots],
  );

  const selectedIndex = flat.findIndex((shot) => shot.url === selectedUrl);
  const selected = selectedIndex >= 0 ? flat[selectedIndex] : null;
  const total = flat.length;

  const step = (delta) => {
    if (!total) return;
    const next = (selectedIndex + delta + total) % total;
    setSelectedUrl(flat[next].url);
  };

  useEffect(() => {
    if (!selected) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "ArrowRight") {
        event.preventDefault();
        step(1);
      } else if (event.key === "ArrowLeft") {
        event.preventDefault();
        step(-1);
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  });

  return (
    <div className="view gallery-view">
      <section className="card gallery-toolbar">
        <div className="head-title">
          <span className="head-glyph is-sky">
            <Images size={18} />
          </span>
          <div>
            <h2>视觉留档</h2>
            <p>
              {total
                ? `来自 ${screenshots.length} 次运行，共 ${total} 张关键页面截图。`
                : "任务运行后，关键页面会自动保存到这里。"}
            </p>
          </div>
        </div>
        <button
          type="button"
          className="btn btn-subtle"
          onClick={onRefresh}
          disabled={loading}
        >
          {loading ? <Spinner size={15} /> : <RefreshCw size={15} />}
          {loading ? "刷新中" : "刷新截图"}
        </button>
      </section>

      {screenshots.length === 0 ? (
        <section className="gallery-empty">
          <div className="gallery-orbit" aria-hidden="true">
            <span className="gallery-orbit-ring ring-one" />
            <span className="gallery-orbit-ring ring-two" />
            <span className="gallery-orbit-core">
              <Images size={28} />
            </span>
            <span className="gallery-orbit-node node-a" />
            <span className="gallery-orbit-node node-b" />
          </div>
          <h3>等待第一次巡航</h3>
          <p>
            任务启动后，程序会在仪表盘、问答页、领取结果等关键节点截图，
            方便你核对每一步发生了什么。
          </p>
          <span className="gallery-empty-tag">截图只保存在本机 state/screenshots</span>
        </section>
      ) : (
        <div className="run-groups">
          {screenshots.map((group) => (
            <section className="run-group" key={group.run}>
              <div className="run-head">
                <div className="run-title">
                  <span className="run-dot" />
                  <h3>{formatRunId(group.run)}</h3>
                  <span className="run-count">{group.files.length} 张</span>
                </div>
                <span className="run-code">{group.run}</span>
              </div>
              <div className="shot-grid">
                {group.files.map((file) => (
                  <ShotThumb
                    key={file.name}
                    shot={{ ...file, run: group.run }}
                    onOpen={(shot) => setSelectedUrl(shot.url)}
                  />
                ))}
              </div>
            </section>
          ))}
        </div>
      )}

      <Modal
        open={Boolean(selected)}
        onClose={() => setSelectedUrl(null)}
        className="lightbox-dialog"
        labelledBy="lightbox-title"
      >
        {selected ? (
          <>
            <div className="lightbox-view">
              <img
                key={selected.url}
                src={withToken(selected.url)}
                alt={shotLabel(selected.name)}
                draggable="false"
              />
              {total > 1 ? (
                <>
                  <button
                    type="button"
                    className="lightbox-nav is-prev"
                    onClick={() => step(-1)}
                    aria-label="上一张"
                  >
                    <ChevronLeft size={20} />
                  </button>
                  <button
                    type="button"
                    className="lightbox-nav is-next"
                    onClick={() => step(1)}
                    aria-label="下一张"
                  >
                    <ChevronRight size={20} />
                  </button>
                </>
              ) : null}
              <span className="lightbox-counter">
                {selectedIndex + 1} / {total}
              </span>
            </div>
            <div className="lightbox-bar">
              <div className="lightbox-meta">
                <span className="lightbox-run">RUN {formatRunId(selected.run)}</span>
                <h3 id="lightbox-title">{shotLabel(selected.name)}</h3>
                <p>
                  {formatTime(selected.mtime)} · {formatBytes(selected.size)} ·{" "}
                  {selected.name}
                </p>
              </div>
              <a
                className="btn btn-ghost"
                href={withToken(selected.url)}
                download={selected.name}
              >
                <Download size={16} />
                下载原图
              </a>
            </div>
          </>
        ) : null}
      </Modal>
    </div>
  );
}
