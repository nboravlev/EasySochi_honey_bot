import { createContext, useCallback, useContext, useEffect, useRef, useState, type ReactNode } from "react";

import { ApiError } from "../api";

export function errorText(e: unknown): string {
  return e instanceof ApiError ? e.message : "Что-то пошло не так.";
}

// --- тосты: короткие сообщения о результате действия

type Tone = "ok" | "warn" | "error";
interface Toast {
  id: number;
  text: string;
  tone: Tone;
}

const ToastContext = createContext<(text: string, tone?: Tone) => void>(() => undefined);

export function ToastProvider({ children }: { children: ReactNode }) {
  const [toasts, setToasts] = useState<Toast[]>([]);
  const nextId = useRef(1);
  const show = useCallback((text: string, tone: Tone = "ok") => {
    const id = nextId.current++;
    setToasts((t) => [...t, { id, text, tone }]);
    setTimeout(() => setToasts((t) => t.filter((x) => x.id !== id)), tone === "error" ? 8000 : 4000);
  }, []);
  return (
    <ToastContext.Provider value={show}>
      {children}
      <div className="toasts" role="status" aria-live="polite">
        {toasts.map((t) => (
          <div key={t.id} className={`toast toast--${t.tone}`}>
            {t.text}
          </div>
        ))}
      </div>
    </ToastContext.Provider>
  );
}

export const useToast = () => useContext(ToastContext);

/** Выполнить действие с индикатором и тостом ошибки. */
export function useAction() {
  const toast = useToast();
  const [busy, setBusy] = useState(false);
  const run = useCallback(
    async <T,>(action: () => Promise<T>, success?: string): Promise<T | undefined> => {
      setBusy(true);
      try {
        const result = await action();
        if (success) toast(success);
        return result;
      } catch (e) {
        toast(errorText(e), "error");
        return undefined;
      } finally {
        setBusy(false);
      }
    },
    [toast],
  );
  return { busy, run };
}

/** Загрузка данных: data / error / reload. */
export function useData<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [version, setVersion] = useState(0);
  useEffect(() => {
    let cancelled = false;
    setError(null);
    load()
      .then((value) => !cancelled && setData(value))
      .catch((e: unknown) => !cancelled && setError(errorText(e)));
    return () => {
      cancelled = true;
    };
    // deps задаёт вызывающий
  }, [version, ...deps]);
  return { data, setData, error, reload: () => setVersion((v) => v + 1) };
}

export function Loading() {
  return (
    <div className="a-state" role="status">
      <div className="spinner" aria-hidden="true" /> Загружаем…
    </div>
  );
}

export function Failure({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="a-state a-state--error" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button className="a-btn a-btn--ghost" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Field({ label, hint, children }: { label: string; hint?: string; children: ReactNode }) {
  return (
    <label className="a-field">
      <span className="a-field__label">{label}</span>
      {children}
      {hint && <span className="a-field__hint">{hint}</span>}
    </label>
  );
}

export function Badge({ tone, children }: { tone: string; children: ReactNode }) {
  return <span className={`a-badge a-badge--${tone}`}>{children}</span>;
}

export function Card({ title, actions, children }: { title?: ReactNode; actions?: ReactNode; children: ReactNode }) {
  return (
    <section className="a-card">
      {(title || actions) && (
        <header className="a-card__head">
          {title && <h2>{title}</h2>}
          {actions && <div className="a-card__actions">{actions}</div>}
        </header>
      )}
      {children}
    </section>
  );
}
