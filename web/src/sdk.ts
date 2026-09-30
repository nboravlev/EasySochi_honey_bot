// SDK Telegram Mini App грузим только когда страницу открыл Telegram: посетителю обычного сайта
// не нужно ждать telegram.org (из России он бывает медленным или недоступен).
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

export async function loadTelegramSdk(): Promise<void> {
  await loadScript(TELEGRAM_SDK).catch((e) => console.warn("Telegram SDK:", e));
}
