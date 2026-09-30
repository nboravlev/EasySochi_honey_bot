// Обёртка над Telegram Mini App SDK (telegram-web-app.js из index.html).
// Вне Telegram SDK тоже загружен, но initData пустая — тогда витрина работает только на просмотр.

interface TelegramButton {
  setText(text: string): void;
  show(): void;
  hide(): void;
  enable(): void;
  disable(): void;
  showProgress(leaveActive?: boolean): void;
  hideProgress(): void;
  onClick(cb: () => void): void;
  offClick(cb: () => void): void;
}

interface WebApp {
  initData: string;
  initDataUnsafe: {
    user?: { id: number; first_name: string; allows_write_to_pm?: boolean };
    start_param?: string;
  };
  platform: string;
  ready(): void;
  expand(): void;
  MainButton: TelegramButton;
  BackButton: Omit<TelegramButton, "setText" | "enable" | "disable" | "showProgress" | "hideProgress">;
  HapticFeedback?: { notificationOccurred(type: "error" | "success" | "warning"): void };
  requestWriteAccess?(cb?: (allowed: boolean) => void): void;
  openLink(url: string): void;
  openTelegramLink(url: string): void;
  showAlert?(message: string, cb?: () => void): void;
}

declare global {
  interface Window {
    Telegram?: { WebApp?: WebApp };
  }
}

export const webApp: WebApp | undefined = typeof window === "undefined" ? undefined : window.Telegram?.WebApp;

/** Открыто внутри Telegram с подписанными данными пользователя — можно заказывать. */
export const insideTelegram = Boolean(webApp?.initData);

export function initTelegram(): void {
  if (!insideTelegram || !webApp) return;
  webApp.ready();
  webApp.expand();
}

/** Бот пишет покупателю статусы заказа — для этого нужно разрешение писать в личку. */
export function ensureWriteAccess(): Promise<boolean> {
  const user = webApp?.initDataUnsafe.user;
  if (!webApp?.requestWriteAccess || !user || user.allows_write_to_pm) return Promise.resolve(true);
  return new Promise((resolve) => webApp.requestWriteAccess!((allowed) => resolve(allowed)));
}

export function haptic(type: "error" | "success" | "warning"): void {
  webApp?.HapticFeedback?.notificationOccurred(type);
}

export function openExternal(url: string): void {
  if (insideTelegram && webApp) {
    if (url.startsWith("https://t.me/")) webApp.openTelegramLink(url);
    else webApp.openLink(url);
  } else {
    window.open(url, "_blank", "noopener");
  }
}

