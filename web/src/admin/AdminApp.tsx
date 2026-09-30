import { useEffect, useState } from "react";

import { ApiError } from "../api";
import { adminApi } from "./api";
import { OrdersPage } from "./pages/OrdersPage";
import { ProductsPage } from "./pages/ProductsPage";
import { QueuePage } from "./pages/QueuePage";
import { ShopsPage } from "./pages/ShopsPage";
import { StatsPage } from "./pages/StatsPage";
import type { AdminMe } from "./types";
import { Failure, Loading, ToastProvider, useData } from "./ui";

type Section = "orders" | "products" | "stats" | "shops" | "queue";

const SECTIONS: { id: Section; title: string; ownerOnly?: boolean }[] = [
  { id: "orders", title: "Заказы" },
  { id: "products", title: "Товары" },
  { id: "stats", title: "Статистика" },
  { id: "shops", title: "Магазины" },
  { id: "queue", title: "Очередь", ownerOnly: true },
];

const SECTION_KEY = "admin_section";

function savedSection(): Section {
  try {
    const value = window.localStorage.getItem(SECTION_KEY) as Section | null;
    return value && SECTIONS.some((s) => s.id === value) ? value : "orders";
  } catch {
    return "orders";
  }
}

type Auth = { state: "loading" } | { state: "in"; me: AdminMe } | { state: "out"; message: string; status: number };

export function AdminApp({ loginError }: { loginError: string | null }) {
  const [auth, setAuth] = useState<Auth>({ state: "loading" });

  useEffect(() => {
    adminApi.me()
      .then((me) => setAuth({ state: "in", me }))
      .catch((e: unknown) => setAuth({
        state: "out", status: e instanceof ApiError ? e.status : 0,
        message: e instanceof ApiError ? e.message : "Не удалось открыть админку.",
      }));
  }, []);

  if (auth.state === "loading") return <Loading />;
  if (auth.state === "out") return <LoginScreen message={loginError ?? auth.message} forbidden={auth.status === 403} />;
  return (
    <ToastProvider>
      <Shell me={auth.me} onLogout={() => setAuth({ state: "out", status: 401, message: "Вы вышли из админки." })} />
    </ToastProvider>
  );
}

function LoginScreen({ message, forbidden }: { message: string; forbidden: boolean }) {
  return (
    <div className="a-login">
      <h1>🍯 Админка</h1>
      <p>{message}</p>
      {!forbidden && (
        <ol>
          <li>Откройте чат с ботом в Telegram.</li>
          <li>Отправьте команду <code>/admin</code>.</li>
          <li>Нажмите «Открыть админку» — ссылка действует 10 минут и один раз.</li>
        </ol>
      )}
      <p className="a-muted">В Telegram админка открывается и без ссылки — кнопкой «⚙️ Админка» в меню менеджера.</p>
    </div>
  );
}

function Shell({ me, onLogout }: { me: AdminMe; onLogout: () => void }) {
  const [section, setSection] = useState<Section>(savedSection);
  const [shopId, setShopId] = useState<number | null>(me.is_owner ? null : me.shop?.id ?? null);
  const shops = useData(() => adminApi.shops(), []);

  const open = (next: Section) => {
    setSection(next);
    try {
      window.localStorage.setItem(SECTION_KEY, next);
    } catch {
      // без хранилища просто откроется «Заказы»
    }
  };
  const logout = async () => {
    await adminApi.logout().catch(() => undefined);
    onLogout();
  };
  const visible = SECTIONS.filter((s) => !s.ownerOnly || me.is_owner);
  const current = visible.some((s) => s.id === section) ? section : "orders";

  return (
    <div className="a-app">
      <header className="a-top">
        <div className="a-top__brand">🍯 <b>Админка</b> <span className="a-muted">{me.is_owner ? "владелец платформы" : me.shop?.name}</span></div>
        <nav className="a-nav" aria-label="Разделы">
          {visible.map((s) => (
            <button key={s.id} className={current === s.id ? "is-active" : ""} aria-current={current === s.id ? "page" : undefined}
              onClick={() => open(s.id)}>
              {s.title}
            </button>
          ))}
        </nav>
        <div className="a-top__user">
          {me.is_owner && shops.data && current !== "shops" && current !== "queue" && (
            <select aria-label="Магазин" value={shopId ?? ""} onChange={(e) => setShopId(e.target.value ? Number(e.target.value) : null)}>
              <option value="">Все магазины</option>
              {shops.data.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          )}
          <span>{me.name}</span>
          {me.via === "session" && <button className="a-btn a-btn--ghost" onClick={logout}>Выйти</button>}
        </div>
      </header>

      <main className="a-main">
        {current === "orders" && <OrdersPage shopId={shopId} />}
        {current === "products" && (shops.data ? <ProductsPage me={me} shopId={shopId} shops={shops.data} /> : <Loading />)}
        {current === "stats" && <StatsPage shopId={shopId} />}
        {current === "shops" && (shops.error ? <Failure message={shops.error} onRetry={shops.reload} /> : shops.data ?
          <ShopsPage me={me} shops={shops.data} onShopsChanged={shops.reload} /> : <Loading />)}
        {current === "queue" && <QueuePage />}
      </main>
    </div>
  );
}
