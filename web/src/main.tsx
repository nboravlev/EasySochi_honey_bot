// SDK Telegram Mini App подгружаем, только если страницу открыл Telegram: он передаёт параметры
// запуска в адресе (#tgWebAppData=…). Посетителю обычного сайта не нужно ждать telegram.org —
// из России он бывает медленным или недоступен. Модули приложения импортируются после SDK:
// telegram.ts читает window.Telegram при загрузке.
const TELEGRAM_SDK = "https://telegram.org/js/telegram-web-app.js";
const SDK_TIMEOUT_MS = 8000;

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement("script");
    script.src = src;
    script.onload = () => resolve();
    script.onerror = () => reject(new Error(`не загрузился ${src}`));
    document.head.appendChild(script);
    setTimeout(() => reject(new Error("таймаут")), SDK_TIMEOUT_MS);
  });
}

async function start() {
  if (window.location.hash.includes("tgWebApp")) {
    await loadScript(TELEGRAM_SDK).catch((e) => console.warn("Telegram SDK:", e));
  }
  const [{ StrictMode, createElement }, { createRoot }, { App }, { initTelegram }] = await Promise.all([
    import("react"),
    import("react-dom/client"),
    import("./App"),
    import("./telegram"),
    import("./styles.css"),
  ]);
  initTelegram();
  createRoot(document.getElementById("root")!).render(createElement(StrictMode, null, createElement(App)));
}

void start();
