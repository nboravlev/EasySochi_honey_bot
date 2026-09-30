// Где открыта витрина, определяется по адресу:
// - Telegram передаёт параметры запуска в хеше (#tgWebAppData=…) — тогда подгружаем SDK Telegram;
// - VK — в query (?vk_app_id=…&sign=…) — тогда VK Bridge;
// - иначе обычный браузер: каталог на просмотр.
// SDK Telegram грузится только для Telegram: посетителю сайта не нужно ждать telegram.org
// (из России он бывает медленным или недоступен). Модули приложения импортируются после SDK:
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
  const fromTelegram = window.location.hash.includes("tgWebApp");
  if (fromTelegram) {
    await loadScript(TELEGRAM_SDK).catch((e) => console.warn("Telegram SDK:", e));
  }
  const [{ StrictMode, createElement }, { createRoot }, { App }, { initTelegram }, platforms] = await Promise.all([
    import("react"),
    import("react-dom/client"),
    import("./App"),
    import("./telegram"),
    import("./platform"),
    import("./styles.css"),
  ]);

  if (platforms.isVkLaunch()) {
    const { default: bridge } = await import("@vkontakte/vk-bridge");
    platforms.followVkAppearance(bridge);
    if (bridge.isEmbedded()) void bridge.send("VKWebAppInit").catch((e) => console.warn("VK Bridge:", e));
    platforms.setPlatform(platforms.vkPlatform(bridge));
  } else if (fromTelegram) {
    initTelegram();
    platforms.setPlatform(platforms.telegramPlatform());
  }

  createRoot(document.getElementById("root")!).render(createElement(StrictMode, null, createElement(App)));
}

void start();
