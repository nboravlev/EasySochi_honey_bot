// Клиент API админки. Вход — подпись Telegram (Mini App) или cookie сессии (браузер, ссылка от бота).
// Заголовок X-Honey-Admin отправляется всегда: без него сервер не примет изменяющий запрос по cookie (CSRF).
import { ApiError, errorMessage } from "../api";
import type {
  AdminLocation,
  AdminMe,
  AdminOrder,
  AdminProduct,
  AdminShop,
  DeliveryResult,
  Manager,
  OrderPage,
  QueuedNotification,
  Reference,
  StaffAction,
  Stats,
} from "./types";

let telegramInitData: string | null = null;

export function setTelegramAuth(initData: string): void {
  telegramInitData = initData;
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  const headers: Record<string, string> = { "X-Honey-Admin": "1" };
  if (!(init.body instanceof FormData)) headers["Content-Type"] = "application/json";
  if (telegramInitData) headers.Authorization = `tma ${telegramInitData}`;
  let response: Response;
  try {
    response = await fetch(`/api/admin${path}`, { credentials: "same-origin", ...init, headers: { ...headers, ...init.headers } });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Проверьте интернет.");
  }
  if (response.status === 204) return undefined as T;
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body as T;
}

const json = (method: string, data: unknown): RequestInit => ({ method, body: JSON.stringify(data) });

function query(params: Record<string, string | number | null | undefined>): string {
  const entries = Object.entries(params).filter(([, v]) => v !== null && v !== undefined && v !== "");
  return entries.length ? `?${new URLSearchParams(entries.map(([k, v]) => [k, String(v)]))}` : "";
}

export const adminApi = {
  login: (token: string) => request<AdminMe>("/login", json("POST", { token })),
  logout: () => request<void>("/logout", { method: "POST" }),
  me: () => request<AdminMe>("/me"),

  orders: (p: { group: string; q?: string; shop_id?: number | null; offset?: number }) =>
    request<OrderPage>(`/orders${query({ ...p, limit: 50 })}`),
  order: (id: number) => request<AdminOrder>(`/orders/${id}`),
  act: (id: number, action: StaffAction, reason = "") =>
    request<{ order: AdminOrder; customer_notified: DeliveryResult }>(`/orders/${id}/actions`, json("POST", { action, reason })),

  reference: () => request<Reference>("/reference"),
  createType: (name: string) => request<{ id: number; name: string }>("/types", json("POST", { name })),
  products: (shopId?: number | null) => request<AdminProduct[]>(`/products${query({ shop_id: shopId })}`),
  createProduct: (data: {
    shop_id: number | null;
    name: string;
    type_id: number;
    description: string;
    offers: { size_id: number; price: string }[];
  }) => request<AdminProduct>("/products", json("POST", data)),
  updateProduct: (id: number, data: { name?: string; type_id?: number; description?: string }) =>
    request<AdminProduct>(`/products/${id}`, json("PATCH", data)),
  setOffers: (id: number, offers: { size_id: number; price: string; active: boolean }[]) =>
    request<AdminProduct>(`/products/${id}/offers`, json("PUT", offers)),
  uploadPhoto: (id: number, file: File) => {
    const form = new FormData();
    form.append("file", file);
    return request<AdminProduct>(`/products/${id}/photos`, { method: "POST", body: form });
  },
  removePhoto: (id: number, imageId: number) =>
    request<AdminProduct>(`/products/${id}/photos/${imageId}`, { method: "DELETE" }),
  publish: (id: number) => request<AdminProduct>(`/products/${id}/publish`, { method: "POST" }),
  withdraw: (id: number) => request<AdminProduct>(`/products/${id}/withdraw`, { method: "POST" }),

  shops: () => request<AdminShop[]>("/shops"),
  createShop: (data: { slug: string; name: string; phone: string }) => request<AdminShop>("/shops", json("POST", data)),
  updateShop: (id: number, data: { name?: string; phone?: string; is_active?: boolean }) =>
    request<AdminShop>(`/shops/${id}`, json("PATCH", data)),
  setStaffChat: (id: number, chatId: number | null) =>
    request<AdminShop>(`/shops/${id}/staff-chat`, json("PUT", { telegram_chat_id: chatId })),
  addLocation: (shopId: number, data: Omit<AdminLocation, "id">) =>
    request<AdminShop>(`/shops/${shopId}/locations`, json("POST", data)),
  updateLocation: (id: number, data: Omit<AdminLocation, "id">) =>
    request<AdminShop>(`/locations/${id}`, json("PUT", data)),
  managers: () => request<Manager[]>("/managers"),
  addManager: (user: string, shopId: number) => request<Manager>("/managers", json("POST", { user, shop_id: shopId })),
  removeManager: (userId: number) => request<void>(`/managers/${userId}`, { method: "DELETE" }),

  stats: (days: number | null, shopId?: number | null) => request<Stats>(`/stats${query({ days, shop_id: shopId })}`),
  notifications: (status: "failed" | "pending") => request<QueuedNotification[]>(`/notifications${query({ status })}`),
  retry: (id: number) => request<DeliveryResult>(`/notifications/${id}/retry`, { method: "POST" }),
};
