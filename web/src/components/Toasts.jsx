import { AnimatePresence, motion } from "framer-motion";
import { AlertTriangle, CheckCircle2, Info, X } from "lucide-react";

const ICONS = {
  success: CheckCircle2,
  error: AlertTriangle,
  info: Info,
};

export default function Toasts({ items, onDismiss }) {
  return (
    <div className="toast-stack" role="status" aria-live="polite">
      <AnimatePresence initial={false}>
        {items.map((toast) => {
          const Icon = ICONS[toast.tone] || Info;
          return (
            <motion.div
              key={toast.id}
              layout
              className={`toast toast-${toast.tone || "info"}`}
              initial={{ opacity: 0, y: 18, scale: 0.96 }}
              animate={{ opacity: 1, y: 0, scale: 1 }}
              exit={{ opacity: 0, x: 26, transition: { duration: 0.18 } }}
              transition={{ duration: 0.26, ease: [0.22, 1, 0.36, 1] }}
            >
              <span className="toast-icon">
                <Icon size={18} />
              </span>
              <div className="toast-content">
                <strong>{toast.title}</strong>
                {toast.message ? <p>{toast.message}</p> : null}
              </div>
              <button
                type="button"
                className="toast-close"
                onClick={() => onDismiss(toast.id)}
                aria-label="关闭提示"
              >
                <X size={15} />
              </button>
              <span className="toast-timer" />
            </motion.div>
          );
        })}
      </AnimatePresence>
    </div>
  );
}
