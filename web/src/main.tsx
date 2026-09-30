// Где открыта витрина, определяется по адресу:
// - Telegram передаёт параметры запуска в хеше (#tgWebAppData=…) — тогда подгружаем SDK Telegram;
// - VK — в query (?vk_app_id=…&sign=…) — тогда VK Bridge;
// - иначе обычный браузер: каталог на просмотр.
// SDK Telegram грузится только для Telegram (sdk.ts). Модули приложения импортируются после SDK:
// telegram.ts читает window.Telegram при загрузке.
import { loadTelegramSdk } from "./sdk";

async function start() {
  const fromTelegram = window.location.hash.includes("tgWebApp");
  if (fromTelegram) {
    await loadTelegramSdk();
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
