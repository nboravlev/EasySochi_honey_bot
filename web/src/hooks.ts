import { useEffect, useRef, useState } from "react";

import { ApiError } from "./api";
import { insideTelegram, webApp } from "./telegram";

/** Загрузка данных с состоянием «загружается / ошибка / готово» и повтором. */
export function useLoad<T>(load: () => Promise<T>, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let cancelled = false;
    setError(null);
    load()
      .then((value) => !cancelled && setData(value))
      .catch((e: unknown) => !cancelled && setError(e instanceof ApiError ? e.message : "Что-то пошло не так."));
    return () => {
      cancelled = true;
    };
    // deps задаёт вызывающий: load — новая функция при каждом рендере
  }, [attempt, ...deps]);

  return { data, error, retry: () => setAttempt((n) => n + 1) };
}

/** Главная кнопка Telegram внизу экрана. Вне Telegram ничего не делает — экран рисует свою кнопку. */
export function useMainButton(text: string | null, onClick: () => void, progress = false) {
  const handler = useRef(onClick);
  handler.current = onClick;

  useEffect(() => {
    if (!insideTelegram || !webApp) return;
    const button = webApp.MainButton;
    const click = () => handler.current();
    if (text === null) {
      button.hide();
      return;
    }
    button.setText(text);
    button.show();
    button.onClick(click);
    return () => {
      button.offClick(click);
      button.hide();
    };
  }, [text]);

  useEffect(() => {
    if (!insideTelegram || !webApp || text === null) return;
    if (progress) {
      webApp.MainButton.showProgress(false);
      webApp.MainButton.disable();
    } else {
      webApp.MainButton.hideProgress();
      webApp.MainButton.enable();
    }
  }, [progress, text]);
}

/** Кнопка «Назад» в шапке Telegram. */
export function useBackButton(onBack: (() => void) | null) {
  const handler = useRef(onBack);
  handler.current = onBack;
  const visible = onBack !== null;

  useEffect(() => {
    if (!insideTelegram || !webApp) return;
    const back = webApp.BackButton;
    if (!visible) {
      back.hide();
      return;
    }
    const click = () => handler.current?.();
    back.show();
    back.onClick(click);
    return () => {
      back.offClick(click);
    };
  }, [visible]);
}
