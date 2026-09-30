import { useState } from "react";

import { dateTime } from "../../format";
import { adminApi } from "../api";
import { Card, Failure, Loading, useAction, useData, useToast } from "../ui";
import { deliveryNote } from "./OrdersPage";

const KINDS: Record<string, string> = {
  order_created: "новый заказ (продавцу)",
  order_placed: "заказ создан (покупателю)",
  order_confirmed: "заказ подтверждён",
  order_ready: "заказ готов",
  order_received: "заказ выдан",
  order_declined: "заказ отклонён",
  order_pickup_planned: "дата получения (продавцу)",
  order_admin_action: "действие в админке (продавцу)",
  tasting_invite: "приглашение на дегустацию",
  manager_added: "назначение менеджером",
  manager_removed: "снятие менеджера",
  user_problem: "сообщение о проблеме",
  support_reply: "ответ поддержки",
};

export function QueuePage() {
  const [status, setStatus] = useState<"failed" | "pending">("failed");
  const { data, error, reload } = useData(() => adminApi.notifications(status), [status]);
  const { busy, run } = useAction();
  const toast = useToast();

  const retry = async (id: number) => {
    const result = await run(() => adminApi.retry(id));
    if (!result) return;
    toast(result.sent ? "Отправлено." : deliveryNote(result), result.sent ? "ok" : "warn");
    reload();
  };

  return (
    <Card
      title="Очередь уведомлений"
      actions={
        <div className="a-tabs" role="tablist">
          <button role="tab" aria-selected={status === "failed"} className={status === "failed" ? "is-active" : ""} onClick={() => setStatus("failed")}>Не доставлены</button>
          <button role="tab" aria-selected={status === "pending"} className={status === "pending" ? "is-active" : ""} onClick={() => setStatus("pending")}>Ждут повтора</button>
        </div>
      }
    >
      <p className="a-muted">
        Уведомления, которые не ушли сразу. «Ждут повтора» бот досылает сам; «Не доставлены» — человек заблокировал
        бота, запретил сообщения или попытки кончились. Отправить заново можно, когда причина устранена.
      </p>
      {error ? <Failure message={error} onRetry={reload} /> : !data ? <Loading /> : data.length === 0 ? (
        <div className="a-state">Пусто — всё доставлено 🎉</div>
      ) : (
        <table className="a-table">
          <thead><tr><th>Когда</th><th>Что</th><th>Куда</th><th>Попыток</th><th>Ошибка</th><th /></tr></thead>
          <tbody>
            {data.map((n) => (
              <tr key={n.id}>
                <td>{dateTime(n.created_at)}</td>
                <td title={n.text}>{KINDS[n.kind] ?? n.kind}<div className="a-muted a-clip">{n.text}</div></td>
                <td>{n.provider}{n.user_id ? ` · пользователь ${n.user_id}` : n.shop_id ? ` · магазин ${n.shop_id}` : ""}</td>
                <td>{n.attempts}</td>
                <td className="a-clip">{n.last_error}</td>
                <td><button className="a-btn a-btn--ghost" disabled={busy} onClick={() => retry(n.id)}>Отправить</button></td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </Card>
  );
}
