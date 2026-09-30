// Где открыта витрина: Telegram Mini App, VK Mini App или обычный браузер.
// Экраны спрашивают у платформы «можно ли заказывать», «есть ли родная кнопка» и т.п.
// и не знают про конкретный мессенджер. Платформа выбирается один раз при старте (main.tsx).
import { ensureWriteAccess, haptic as telegramHaptic, insideTelegram, openExternal as telegramOpen, webApp } from "./telegram";

export type PlatformName = "telegram" | "vk" | "web";

export interface Platform {
  name: PlatformName;
  /** есть подписанный вход — можно оформлять заказ и смотреть «Мои заказы» */
  canOrder: boolean;
  /** кнопка «Заказать» — родная кнопка платформы (Telegram MainButton), иначе рисуем свою */
  nativeMainButton: boolean;
  /** кнопка «Назад» в шапке платформы, иначе рисуем свою */
  nativeBackButton: boolean;
  /** куда придут уведомления о заказе — для текста «Заказ создан» */
  notificationsHint: string;
  authHeader(): Record<string, string>;
  /** параметр запуска со ссылки (товар): Telegram startapp, VK — #product=12 */
  startParam(): string | undefined;
  /** перед первым заказом: разрешение писать человеку (Telegram — в личку, VK — от сообщества) */
  prepareOrder(options: { vkGroupId: number | null }): Promise<boolean>;
  /** имя из профиля платформы, если сервер его не знает (VK не передаёт имя в параметрах запуска) */
  profileName(): Promise<string | null>;
  haptic(type: "error" | "success" | "warning"): void;
  openExternal(url: string): void;
}

const WEB_HINT = "Продавец подтвердит заказ — уведомление придёт в чат с ботом.";

export const webPlatform: Platform = {
  name: "web",
  canOrder: false,
  nativeMainButton: false,
  nativeBackButton: false,
  notificationsHint: WEB_HINT,
  authHeader: () => ({}),
  startParam: () => undefined,
  prepareOrder: async () => true,
  profileName: async () => null,
  haptic: () => undefined,
  openExternal: (url) => void window.open(url, "_blank", "noopener"),
};

export function telegramPlatform(): Platform {
  return {
    name: "telegram",
    canOrder: insideTelegram,
    nativeMainButton: true,
    nativeBackButton: true,
    notificationsHint: WEB_HINT,
    authHeader: (): Record<string, string> => (webApp ? { Authorization: `tma ${webApp.initData}` } : {}),
    startParam: () => webApp?.initDataUnsafe.start_param,
    prepareOrder: () => ensureWriteAccess(),
    profileName: async () => webApp?.initDataUnsafe.user?.first_name ?? null,
    haptic: telegramHaptic,
    openExternal: telegramOpen,
  };
}

/** Параметры запуска VK Mini App в адресе: vk_app_id, vk_user_id, …, sign. */
export function isVkLaunch(search: string = window.location.search): boolean {
  const params = new URLSearchParams(search);
  return params.has("vk_app_id") && params.has("sign");
}

type VkBridge = typeof import("@vkontakte/vk-bridge").default;

const VK_MESSAGES_ALLOWED = "vk_messages_allowed";
// диалог разрешения ждёт человека; остальное — быстрые вызовы. Без ответа VK (старый клиент,
// страница открыта не внутри VK) не зависаем: заказ оформляется и без разрешения
const VK_DIALOG_TIMEOUT_MS = 60_000;
const VK_CALL_TIMEOUT_MS = 5_000;

export function withTimeout<T>(promise: Promise<T>, ms: number): Promise<T> {
  return new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("VK Bridge не ответил")), ms);
    promise.then(
      (value) => {
        clearTimeout(timer);
        resolve(value);
      },
      (error) => {
        clearTimeout(timer);
        reject(error);
      },
    );
  });
}

function remembered(key: string): boolean {
  try {
    return window.localStorage.getItem(key) === "1";
  } catch {
    return false;
  }
}

function remember(key: string): void {
  try {
    window.localStorage.setItem(key, "1");
  } catch {
    // хранилище недоступно (приватный режим) — спросим ещё раз в следующий раз
  }
}

export function vkPlatform(bridge: VkBridge, search: string = window.location.search): Platform {
  // подпись проверяет сервер; параметры берём с первой загрузки — адрес внутри приложения не меняется
  const launchParams = search.replace(/^\?/, "");
  // вне iframe / WebView VK (например, ссылку открыли в браузере) Bridge не отвечает — не вызываем
  const embedded = bridge.isEmbedded();
  return {
    name: "vk",
    canOrder: true,
    nativeMainButton: false,
    nativeBackButton: false,
    notificationsHint: "Продавец подтвердит заказ — уведомление придёт в сообщения сообщества ВКонтакте.",
    authHeader: () => ({ Authorization: `vk ${launchParams}` }),
    startParam: () => window.location.hash.replace(/^#/, "") || undefined,
    async prepareOrder({ vkGroupId }) {
      if (!embedded || !vkGroupId || remembered(VK_MESSAGES_ALLOWED)) return true;
      try {
        const { result } = await withTimeout(
          bridge.send("VKWebAppAllowMessagesFromGroup", { group_id: vkGroupId }),
          VK_DIALOG_TIMEOUT_MS,
        );
        if (result) remember(VK_MESSAGES_ALLOWED);
        return result;
      } catch {
        return false; // отказался — заказ всё равно оформим, статус будет виден в «Мои заказы»
      }
    },
    async profileName() {
      if (!embedded) return null;
      try {
        return (await withTimeout(bridge.send("VKWebAppGetUserInfo"), VK_CALL_TIMEOUT_MS)).first_name || null;
      } catch {
        return null;
      }
    },
    haptic: (type) => {
      if (embedded) void bridge.send("VKWebAppTapticNotificationOccurred", { type }).catch(() => undefined);
    },
    openExternal: (url) => void window.open(url, "_blank", "noopener"),
  };
}

/** Светлая/тёмная тема VK: VK сообщает её событием VKWebAppUpdateConfig. */
export function followVkAppearance(bridge: VkBridge): void {
  bridge.subscribe((event) => {
    const { type, data } = event.detail as { type: string; data?: { appearance?: string } };
    if (type === "VKWebAppUpdateConfig" && (data?.appearance === "dark" || data?.appearance === "light")) {
      document.documentElement.dataset.appearance = data.appearance;
    }
  });
}

let current: Platform = webPlatform;

export function setPlatform(platform: Platform): void {
  current = platform;
}

export function platform(): Platform {
  return current;
}

/** Товар, на который ведёт ссылка: параметр запуска «product_12» / «product=12» или сайт ?product=12. */
export function linkedProductId(startParam?: string, search: string = window.location.search): number | null {
  const fromStart = startParam?.match(/^product[_=](\d+)$/)?.[1];
  const fromQuery = new URLSearchParams(search).get("product");
  const value = Number(fromStart ?? fromQuery);
  return Number.isInteger(value) && value > 0 ? value : null;
}
