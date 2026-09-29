import type { ReactNode } from "react";

export function Loader() {
  return (
    <div className="state" role="status">
      <div className="spinner" aria-hidden="true" />
      Загружаем…
    </div>
  );
}

export function ErrorBox({ message, onRetry }: { message: string; onRetry?: () => void }) {
  return (
    <div className="state state--error" role="alert">
      <p>{message}</p>
      {onRetry && (
        <button className="button button--secondary" onClick={onRetry}>
          Повторить
        </button>
      )}
    </div>
  );
}

export function Photo({ src, alt, className = "" }: { src?: string; alt: string; className?: string }) {
  return src ? (
    <img className={`photo ${className}`} src={src} alt={alt} loading="lazy" />
  ) : (
    <div className={`photo photo--empty ${className}`} role="img" aria-label={alt}>
      🍯
    </div>
  );
}

export function Section({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <section className="section">
      {title && <h2 className="section__title">{title}</h2>}
      {children}
    </section>
  );
}

export type Tab = "catalog" | "orders";

export function TabBar({ active, onSelect }: { active: Tab; onSelect: (tab: Tab) => void }) {
  return (
    <nav className="tabbar" aria-label="Разделы">
      <button className={active === "catalog" ? "tabbar__item is-active" : "tabbar__item"} onClick={() => onSelect("catalog")}>
        🍯 Каталог
      </button>
      <button className={active === "orders" ? "tabbar__item is-active" : "tabbar__item"} onClick={() => onSelect("orders")}>
        📦 Мои заказы
      </button>
    </nav>
  );
}
