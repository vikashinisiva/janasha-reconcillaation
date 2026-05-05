import { useEffect, useRef, useState } from "react";

const MIN_SCALE = 0.2;
const MAX_SCALE = 8;
const ZOOM_STEP = 1.2;
const WHEEL_SENSITIVITY = 0.0015;

const IMAGE_EXT = /\.(jpe?g|png)$/i;
const IMAGE_MIME = /^image\/(jpeg|png)$/;

function filterImageFiles(list) {
  return Array.from(list || []).filter(
    (f) => IMAGE_MIME.test(f.type) || IMAGE_EXT.test(f.name)
  );
}

function UploadIcon() {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.5"
      strokeLinecap="square"
      strokeLinejoin="miter"
      aria-hidden="true"
    >
      <path d="M12 16V4" />
      <path d="M6 10L12 4L18 10" />
      <path d="M4 20H20" />
    </svg>
  );
}

export default function LedgerPanel({
  branch,
  photos,
  onUpload,
  readOnly = false,
}) {
  const [currentIdx, setCurrentIdx] = useState(0);
  const [scale, setScale] = useState(1);
  const [offset, setOffset] = useState({ x: 0, y: 0 });
  const [isDragging, setIsDragging] = useState(false);

  const stageRef = useRef(null);
  const dragStartRef = useRef(null);

  const current = photos[currentIdx];

  // Reset zoom/pan whenever the visible photo changes.
  useEffect(() => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  }, [currentIdx]);

  // Keep currentIdx in range if the photo list shrinks externally.
  useEffect(() => {
    if (currentIdx > 0 && currentIdx >= photos.length) {
      setCurrentIdx(Math.max(0, photos.length - 1));
    }
  }, [photos.length, currentIdx]);

  // Wheel zoom — non-passive so we can preventDefault the page scroll.
  useEffect(() => {
    const el = stageRef.current;
    if (!el) return;
    const onWheel = (e) => {
      if (!current) return;
      e.preventDefault();
      const delta = -e.deltaY * WHEEL_SENSITIVITY;
      setScale((s) => Math.max(MIN_SCALE, Math.min(MAX_SCALE, s + delta * s)));
    };
    el.addEventListener("wheel", onWheel, { passive: false });
    return () => el.removeEventListener("wheel", onWheel);
  }, [current]);

  // Pan — window-level mousemove/mouseup so drag continues off the stage.
  useEffect(() => {
    if (!isDragging) return;
    const onMove = (e) => {
      const start = dragStartRef.current;
      if (!start) return;
      setOffset({ x: e.clientX - start.x, y: e.clientY - start.y });
    };
    const onUp = () => {
      setIsDragging(false);
      dragStartRef.current = null;
    };
    window.addEventListener("mousemove", onMove);
    window.addEventListener("mouseup", onUp);
    return () => {
      window.removeEventListener("mousemove", onMove);
      window.removeEventListener("mouseup", onUp);
    };
  }, [isDragging]);

  // Drag-and-drop onto the stage — always active so Priya can add more pages
  // by dropping onto the visible image. Disabled in read-only mode.
  useEffect(() => {
    if (readOnly) return;
    const el = stageRef.current;
    if (!el) return;
    const onOver = (e) => {
      e.preventDefault();
      el.classList.add("dragover");
    };
    const onLeave = () => el.classList.remove("dragover");
    const onDrop = (e) => {
      e.preventDefault();
      el.classList.remove("dragover");
      const files = filterImageFiles(e.dataTransfer.files);
      if (files.length) onUpload(files);
    };
    el.addEventListener("dragover", onOver);
    el.addEventListener("dragenter", onOver);
    el.addEventListener("dragleave", onLeave);
    el.addEventListener("drop", onDrop);
    return () => {
      el.removeEventListener("dragover", onOver);
      el.removeEventListener("dragenter", onOver);
      el.removeEventListener("dragleave", onLeave);
      el.removeEventListener("drop", onDrop);
    };
  }, [onUpload, readOnly]);

  const handleMouseDown = (e) => {
    if (!current) return;
    setIsDragging(true);
    dragStartRef.current = { x: e.clientX - offset.x, y: e.clientY - offset.y };
  };

  const handleFilePick = (e) => {
    const files = filterImageFiles(e.target.files);
    if (files.length) onUpload(files);
    e.target.value = "";
  };

  const zoomIn = () => setScale((s) => Math.min(MAX_SCALE, s * ZOOM_STEP));
  const zoomOut = () => setScale((s) => Math.max(MIN_SCALE, s / ZOOM_STEP));
  const resetView = () => {
    setScale(1);
    setOffset({ x: 0, y: 0 });
  };
  const download = () => {
    if (!current) return;
    const a = document.createElement("a");
    a.href = current.url;
    a.download = current.name || "ledger.jpg";
    document.body.appendChild(a);
    a.click();
    a.remove();
  };

  return (
    <aside className="ledger-panel">
      <div className="ledger-head">
        <span className="ledger-title">{branch} LEDGER</span>
        {current && (
          <div className="ledger-tools">
            <button
              type="button"
              className="ledger-tool-btn"
              onClick={zoomIn}
              title="Zoom in"
              aria-label="Zoom in"
            >
              +
            </button>
            <button
              type="button"
              className="ledger-tool-btn"
              onClick={zoomOut}
              title="Zoom out"
              aria-label="Zoom out"
            >
              &minus;
            </button>
            <button
              type="button"
              className="ledger-tool-btn"
              onClick={resetView}
              title="Reset view"
            >
              Reset
            </button>
            <button
              type="button"
              className="ledger-tool-btn"
              onClick={download}
              title="Download"
            >
              Download
            </button>
          </div>
        )}
      </div>

      <div
        className={`ledger-stage ${isDragging ? "dragging" : ""} ${current ? "" : "empty"}`}
        ref={stageRef}
        onMouseDown={handleMouseDown}
      >
        {current ? (
          <img
            src={current.url}
            alt={current.name}
            draggable={false}
            style={{
              transform: `translate(${offset.x}px, ${offset.y}px) scale(${scale})`,
            }}
          />
        ) : readOnly ? (
          <div className="ledger-empty">
            <div className="ledger-empty-icon">
              <UploadIcon />
            </div>
            <div className="ledger-empty-text">No ledger photos uploaded</div>
          </div>
        ) : (
          <label className="ledger-drop">
            <input
              type="file"
              accept="image/jpeg,image/png"
              multiple
              hidden
              onChange={handleFilePick}
            />
            <div className="ledger-drop-icon">
              <UploadIcon />
            </div>
            <div className="ledger-drop-text">Drop ledger photo here</div>
            <div className="ledger-drop-sub">or click to choose &middot; jpg, png</div>
          </label>
        )}
      </div>

      {photos.length > 0 && (
        <div className="ledger-thumbs">
          <span className="ledger-thumbs-label">
            Page {currentIdx + 1} of {photos.length}
          </span>
          <div className="ledger-thumb-strip">
            {photos.map((p, i) => (
              <button
                key={p.id}
                type="button"
                className={`ledger-thumb ${i === currentIdx ? "active" : ""}`}
                onClick={() => setCurrentIdx(i)}
                title={p.name}
              >
                <img src={p.url} alt={p.name} draggable={false} />
              </button>
            ))}
            {!readOnly && (
              <label className="ledger-thumb-add" title="Add page">
                <input
                  type="file"
                  accept="image/jpeg,image/png"
                  multiple
                  hidden
                  onChange={handleFilePick}
                />
                +
              </label>
            )}
          </div>
        </div>
      )}
    </aside>
  );
}
