import { platform } from "./platform";
import type { Catalog, Config, Me, Order } from "./types";

export class ApiError extends Error {
  constructor(
    readonly status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Текст ошибки из ответа API: {"detail": "…"} или список ошибок валидации FastAPI. */
export function errorMessage(status: number, body: unknown): string {
  const detail = (body as { detail?: unknown } | null)?.detail;
  if (typeof detail === "string") return detail;
  if (Array.isArray(detail)) return "Проверьте введённые данные.";
  if (status >= 500) return "Сервис временно недоступен. Попробуйте позже.";
  return "Не удалось выполнить запрос.";
}

async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(`/api${path}`, {
      ...init,
      headers: { "Content-Type": "application/json", ...platform().authHeader(), ...init.headers },
    });
  } catch {
    throw new ApiError(0, "Нет связи с сервером. Проверьте интернет.");
  }
  const body = await response.json().catch(() => null);
  if (!response.ok) throw new ApiError(response.status, errorMessage(response.status, body));
  return body as T;
}

export const api = {
  catalog: () => request<Catalog>("/catalog"),
  config: () => request<Config>("/config"),
  me: () => request<Me>("/me"),
  updateMe: (data: { first_name?: string; phone?: string }) =>
    request<Me>("/me", { method: "PATCH", body: JSON.stringify(data) }),
  orders: () => request<Order[]>("/orders"),
  createOrder: (data: { product_size_id: number; quantity: number; comment: string }) =>
    request<Order>("/orders", { method: "POST", body: JSON.stringify(data) }),
};
