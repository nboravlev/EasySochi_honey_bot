// Точка входа админки (/admin/).
// - Открыта из Telegram (кнопка «⚙️ Админка», #tgWebAppData=…) — вход по подписи Telegram.
// - Открыта по ссылке от бота (#login=…) — обменять одноразовый токен на сессию (cookie) и убрать его из адреса.
// - Иначе — действующая сессия или экран «отправьте боту /admin».
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import "../styles.css";
import "./admin.css";
import { ApiError } from "../api";
import { loadTelegramSdk } from "../sdk";
import { AdminApp } from "./AdminApp";
import { adminApi, setTelegramAuth } from "./api";

async function start() {
  const hash = window.location.hash;
  let loginError: string | null = null;

  if (hash.includes("tgWebApp")) {
    await loadTelegramSdk();
    const webApp = window.Telegram?.WebApp;
    if (webApp?.initData) {
      setTelegramAuth(webApp.initData);
      webApp.ready();
      webApp.expand();
    }
  } else if (hash.startsWith("#login=")) {
    const token = decodeURIComponent(hash.slice("#login=".length));
    // токен не должен оставаться в адресе и истории браузера
    window.history.replaceState(null, "", window.location.pathname);
    try {
      await adminApi.login(token);
    } catch (e) {
      loginError = e instanceof ApiError ? e.message : "Не удалось войти по ссылке.";
    }
  }

  createRoot(document.getElementById("root")!).render(
    <StrictMode>
      <AdminApp loginError={loginError} />
    </StrictMode>,
  );
}

void start();
