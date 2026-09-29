import type { Location, OrderStatusCode, Product } from "./types";

/** «1500.00» → «1 500 ₽», «1500.50» → «1 500,50 ₽» (как в боте). */
export function rub(amount: string | number): string {
  const value = Number(amount);
  const digits = Number.isInteger(value) ? 0 : 2;
  const text = value.toLocaleString("ru-RU", { minimumFractionDigits: digits, maximumFractionDigits: digits });
  return `${text.replace(/ /g, " ")} ₽`;
}

/** «0.5» → «0,5 кг», «1.0» → «1 кг». */
export function sizeLabel(size: string): string {
  return `${Number(size).toLocaleString("ru-RU")} кг`;
}

export function minPrice(product: Product): string | null {
  const prices = product.offers.map((o) => Number(o.price));
  return prices.length ? String(Math.min(...prices)) : null;
}

export function dateTime(iso: string): string {
  return new Date(iso).toLocaleString("ru-RU", {
    timeZone: "Europe/Moscow",
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

export function mapUrl(location: Location): string | null {
  if (location.latitude == null || location.longitude == null) return null;
  return `https://yandex.ru/maps/?pt=${location.longitude},${location.latitude}&z=16&l=map`;
}

/** Статус заказа: завершён ли и какого он «цвета» в списке. */
export const STATUS_TONE: Record<OrderStatusCode, "new" | "work" | "ready" | "done" | "declined"> = {
  created: "new",
  processing: "work",
  ready: "ready",
  customer_notified: "ready",
  received: "done",
  declined: "declined",
};
