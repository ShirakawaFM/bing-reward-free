import { useEffect, useRef } from "react";
import { createPortal } from "react-dom";
import { AnimatePresence, motion } from "framer-motion";
import { X } from "lucide-react";

export function Switch({ checked, onChange, disabled = false, label }) {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      aria-label={label}
      className={`switch ${checked ? "is-on" : ""}`}
      onClick={() => {
        if (!disabled) onChange(!checked);
      }}
      disabled={disabled}
    >
      <span className="switch-thumb" />
    </button>
  );
}

export function Segmented({ value, onChange, options, disabled = false }) {
  return (
    <div className={`segmented ${disabled ? "is-disabled" : ""}`}>
      {options.map((option) => {
        const active = option.value === value;
        return (
          <button
            key={option.value}
            type="button"
            className={active ? "is-active" : ""}
            onClick={() => {
              if (!disabled) onChange(option.value);
            }}
            disabled={disabled}
            aria-pressed={active}
          >
            {option.icon ? <option.icon size={14} /> : null}
            <span>{option.label}</span>
          </button>
        );
      })}
    </div>
  );
}

export function Dot({ tone = "idle", pulse = false }) {
  return <span className={`dot dot-${tone} ${pulse ? "is-pulsing" : ""}`} />;
}

export function Modal({
  open,
  onClose,
  children,
  labelledBy,
  className = "",
  closeOnBackdrop = true,
}) {
  const dialogRef = useRef(null);

  useEffect(() => {
    if (!open) return undefined;
    const onKeyDown = (event) => {
      if (event.key === "Escape") onClose?.();
    };
    document.addEventListener("keydown", onKeyDown);
    document.body.classList.add("modal-open");
    const timer = window.setTimeout(() => dialogRef.current?.focus(), 80);
    return () => {
      document.removeEventListener("keydown", onKeyDown);
      document.body.classList.remove("modal-open");
      window.clearTimeout(timer);
    };
  }, [open, onClose]);

  return createPortal(
    <AnimatePresence>
      {open ? (
        <motion.div
          className="modal-backdrop"
          initial={{ opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{ duration: 0.2 }}
          onMouseDown={(event) => {
            if (closeOnBackdrop && event.target === event.currentTarget) onClose?.();
          }}
        >
          <motion.div
            ref={dialogRef}
            className={`modal-panel ${className}`}
            role="dialog"
            aria-modal="true"
            aria-labelledby={labelledBy}
            tabIndex={-1}
            initial={{ opacity: 0, y: 22, scale: 0.97 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 14, scale: 0.98 }}
            transition={{ duration: 0.28, ease: [0.22, 1, 0.36, 1] }}
          >
            <button
              type="button"
              className="modal-close icon-btn"
              aria-label="关闭"
              onClick={onClose}
            >
              <X size={18} />
            </button>
            {children}
          </motion.div>
        </motion.div>
      ) : null}
    </AnimatePresence>,
    document.body,
  );
}

export function Spinner({ size = 16 }) {
  return <span className="spinner" style={{ width: size, height: size }} aria-hidden="true" />;
}
