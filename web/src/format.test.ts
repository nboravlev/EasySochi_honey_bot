import { describe, expect, it } from "vitest";

import { errorMessage } from "./api";
import { mapUrl, minPrice, rub, sizeLabel } from "./format";
import { isVkLaunch, linkedProductId, withTimeout } from "./platform";
import type { Product } from "./types";

describe("форматирование", () => {
  it("деньги как в боте", () => {
    expect(rub("1500.00")).toBe("1 500 ₽");
    expect(rub("1500.50")).toBe("1 500,50 ₽");
    expect(rub(750)).toBe("750 ₽");
  });

  it("объём банки", () => {
    expect(sizeLabel("0.5")).toBe("0,5 кг");
    expect(sizeLabel("1.0")).toBe("1 кг");
  });

  it("минимальная цена товара", () => {
    const product = { offers: [{ price: "1500.00" }, { price: "800.00" }] } as unknown as Product;
    expect(minPrice(product)).toBe("800");
    expect(minPrice({ offers: [] } as unknown as Product)).toBeNull();
  });

  it("ссылка на карту — долгота, затем широта", () => {
    const location = { id: 1, name: "Пасека", address: "", opening_hours: null, latitude: 43.67, longitude: 40.2 };
    expect(mapUrl(location)).toBe("https://yandex.ru/maps/?pt=40.2,43.67&z=16&l=map");
    expect(mapUrl({ ...location, latitude: null })).toBeNull();
  });
});

describe("ссылка на товар", () => {
  it("из параметра запуска Mini App и из адреса сайта", () => {
    expect(linkedProductId("product_12", "")).toBe(12);
    expect(linkedProductId(undefined, "?product=7")).toBe(7);
    expect(linkedProductId("promo", "?product=abc")).toBeNull();
    expect(linkedProductId(undefined, "")).toBeNull();
    expect(linkedProductId("product=5", "")).toBe(5); // VK: vk.com/app123#product=5
  });
});

describe("платформа", () => {
  it("запуск из VK — по подписанным параметрам в адресе", () => {
    expect(isVkLaunch("?vk_app_id=1&vk_user_id=2&vk_ts=3&sign=abc")).toBe(true);
    expect(isVkLaunch("?vk_app_id=1")).toBe(false);
    expect(isVkLaunch("?product=1")).toBe(false);
  });

  it("вызов VK Bridge без ответа не вешает заказ", async () => {
    await expect(withTimeout(Promise.resolve(1), 50)).resolves.toBe(1);
    await expect(withTimeout(new Promise(() => undefined), 20)).rejects.toThrow("не ответил");
  });
});

describe("ошибки API", () => {
  it("текст из detail, иначе общий", () => {
    expect(errorMessage(409, { detail: "Этот товар больше не продаётся." })).toBe("Этот товар больше не продаётся.");
    expect(errorMessage(422, { detail: [{ loc: ["body", "quantity"] }] })).toBe("Проверьте введённые данные.");
    expect(errorMessage(502, null)).toMatch(/недоступен/);
  });
});
