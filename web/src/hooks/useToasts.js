import { useCallback, useEffect, useRef, useState } from "react";

let counter = 0;

export function useToasts() {
  const [toasts, setToasts] = useState([]);
  const timers = useRef(new Map());

  const dismiss = useCallback((id) => {
    const timer = timers.current.get(id);
    if (timer) {
      window.clearTimeout(timer);
      timers.current.delete(id);
    }
    setToasts((current) => current.filter((item) => item.id !== id));
  }, []);

  const push = useCallback(
    (toast) => {
      counter += 1;
      const id = `toast-${counter}`;
      const item = {
        id,
        tone: "info",
        duration: 4300,
        ...toast,
      };
      setToasts((current) => [...current.slice(-3), item]);
      const timer = window.setTimeout(() => dismiss(id), item.duration);
      timers.current.set(id, timer);
      return id;
    },
    [dismiss],
  );

  useEffect(
    () => () => {
      timers.current.forEach((timer) => window.clearTimeout(timer));
      timers.current.clear();
    },
    [],
  );

  return { toasts, push, dismiss };
}
