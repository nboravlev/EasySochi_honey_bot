import { useEffect, useState } from "react";

import { dateTime, mapUrl, rub, sizeLabel, STATUS_TONE } from "../../format";
import { adminApi } from "../api";
import type { AdminOrder, DeliveryResult, StaffAction } from "../types";
import { Badge, Failure, Loading, useAction, useData, useToast } from "../ui";

const GROUPS = [
  { id: "new", title: "Новые" },
  { id: "work", title: "В работе" },
  { id: "done", title: "Выданы" },
  { id: "declined", title: "Отклонены" },
  { id: "all", title: "Все" },
] as const;

const ACTION_TITLES: Record<StaffAction, string> = {
  confirm: "✅ Подтвердить",
  ready: "📦 Готов к выдаче",
  received: "🤝 Выдан",
  decline: "Отклонить",
};

const REFRESH_MS = 60_000;

export function deliveryNote(result: DeliveryResult): string {
  if (result.sent) return "Покупатель уведомлён.";
  if (result.queued) return "Покупатель пока не получил уведомление — бот повторит отправку.";
  return "Покупатель не получил уведомление (заблокировал бота или запретил сообщения).";
}

export function OrdersPage({ shopId }: { shopId: number | null }) {
  const [group, setGroup] = useState<string>("new");
  const [search, setSearch] = useState("");
  const [query, setQuery] = useState("");
  const [selected, setSelected] = useState<number | null>(null);
  const [extra, setExtra] = useState<AdminOrder[]>([]);
  const page = useData(() => adminApi.orders({ group, q: query, shop_id: shopId }), [group, query, shopId]);

  // новые заказы появляются сами: раз в минуту и при возврате на вкладку
  useEffect(() => {
    const refresh = () => document.visibilityState === "visible" && page.reload();
    const timer = setInterval(refresh, REFRESH_MS);
    document.addEventListener("visibilitychange", refresh);
    return () => {
      clearInterval(timer);
      document.removeEventListener("visibilitychange", refresh);
    };
  }, []);
  useEffect(() => setExtra([]), [group, query, shopId]);

  const items = [...(page.data?.items ?? []), ...extra];
  const loadMore = async () => {
    const next = await adminApi.orders({ group, q: query, shop_id: shopId, offset: items.length });
    setExtra((e) => [...e, ...next.items]);
  };
  const replace = (order: AdminOrder) => {
    page.setData((p) => p && { ...p, items: p.items.map((o) => (o.id === order.id ? order : o)) });
    setExtra((e) => e.map((o) => (o.id === order.id ? order : o)));
  };

  return (
    <div className={selected ? "a-split a-split--open" : "a-split"}>
      <div className="a-split__main">
        <div className="a-toolbar">
          <div className="a-tabs" role="tablist">
            {GROUPS.map((g) => (
              <button key={g.id} role="tab" aria-selected={group === g.id} className={group === g.id ? "is-active" : ""}
                onClick={() => setGroup(g.id)}>
                {g.title}
              </button>
            ))}
          </div>
          <form className="a-search" onSubmit={(e) => { e.preventDefault(); setQuery(search.trim()); }}>
            <input type="search" placeholder="№ заказа, имя, телефон" value={search} onChange={(e) => setSearch(e.target.value)} />
            <button className="a-btn a-btn--ghost">Найти</button>
          </form>
        </div>

        {page.error ? <Failure message={page.error} onRetry={page.reload} /> : !page.data ? <Loading /> : items.length === 0 ? (
          <div className="a-state">Заказов нет.</div>
        ) : (
          <>
            <ul className="a-list">
              {items.map((o) => (
                <li key={o.id}>
                  <button className={selected === o.id ? "a-row is-active" : "a-row"} onClick={() => setSelected(o.id)}>
                    <span className="a-row__id">№{o.id}</span>
                    <span className="a-row__main">
                      <b>{o.product_name}</b> · {sizeLabel(o.size)} × {o.quantity}
                      <span className="a-muted"> — {o.customer.name ?? "без имени"}{shopId === null && o.shop ? ` · ${o.shop.name}` : ""}</span>
                    </span>
                    <span className="a-row__sum">{rub(o.total)}</span>
                    <span className="a-row__date a-muted">{dateTime(o.created_at)}</span>
                    <Badge tone={STATUS_TONE[o.status.code]}>{o.status.title}</Badge>
                  </button>
                </li>
              ))}
            </ul>
            {items.length < page.data.total && (
              <button className="a-btn a-btn--ghost a-more" onClick={loadMore}>
                Показать ещё ({page.data.total - items.length})
              </button>
            )}
          </>
        )}
      </div>

      {selected !== null && (
        <aside className="a-split__side">
          <OrderDetails orderId={selected} onClose={() => setSelected(null)} onChanged={replace} />
        </aside>
      )}
    </div>
  );
}

function OrderDetails({ orderId, onClose, onChanged }: { orderId: number; onClose: () => void; onChanged: (o: AdminOrder) => void }) {
  const toast = useToast();
  const { data: order, setData, error, reload } = useData(() => adminApi.order(orderId), [orderId]);
  const { busy, run } = useAction();
  const [declining, setDeclining] = useState(false);
  const [reason, setReason] = useState("");
  useEffect(() => setDeclining(false), [orderId]);

  if (error) return <Failure message={error} onRetry={reload} />;
  if (!order) return <Loading />;

  const act = async (action: StaffAction) => {
    const result = await run(() => adminApi.act(order.id, action, action === "decline" ? reason.trim() : ""));
    if (!result) return;
    setData(result.order);
    onChanged(result.order);
    setDeclining(false);
    const note = deliveryNote(result.customer_notified);
    toast(`Заказ №${order.id}: ${result.order.status.title.toLowerCase()}. ${note}`, result.customer_notified.sent ? "ok" : "warn");
  };
  const map = order.pickup ? mapUrl(order.pickup) : null;
  const c = order.customer;

  return (
    <div className="a-details">
      <header className="a-details__head">
        <h2>Заказ №{order.id}</h2>
        <button className="a-icon" aria-label="Закрыть" onClick={onClose}>✕</button>
      </header>
      <Badge tone={STATUS_TONE[order.status.code]}>{order.status.title}</Badge>

      <dl className="a-dl">
        <dt>Товар</dt>
        <dd>{order.product_name} · {sizeLabel(order.size)} × {order.quantity}</dd>
        <dt>Сумма</dt>
        <dd><b>{rub(order.total)}</b></dd>
        <dt>Создан</dt>
        <dd>{dateTime(order.created_at)}</dd>
        <dt>Магазин</dt>
        <dd>{order.shop.name}</dd>
        {order.comment && (<><dt>Комментарий</dt><dd>{order.comment}</dd></>)}
        {order.decline_reason && (<><dt>Причина отказа</dt><dd>{order.decline_reason}</dd></>)}
        {order.manager && (<><dt>Подтвердил</dt><dd>{order.manager}</dd></>)}
        {order.pickup && (
          <>
            <dt>Выдача</dt>
            <dd>{order.pickup.address}{map && <> · <a href={map} target="_blank" rel="noopener">карта</a></>}</dd>
          </>
        )}
      </dl>

      <h3>Покупатель</h3>
      <dl className="a-dl">
        <dt>Имя</dt>
        <dd>{c.name ?? "не указано"}</dd>
        <dt>Телефон</dt>
        <dd>{c.phone ? <a href={`tel:${c.phone.replace(/[^\d+]/g, "")}`}>{c.phone}</a> : "не указан"}</dd>
        {c.telegram_username && (<><dt>Telegram</dt><dd><a href={`https://t.me/${c.telegram_username}`} target="_blank" rel="noopener">@{c.telegram_username}</a></dd></>)}
        {c.vk_url && (<><dt>ВКонтакте</dt><dd><a href={c.vk_url} target="_blank" rel="noopener">профиль</a></dd></>)}
      </dl>

      {order.actions.length > 0 && (
        <div className="a-details__actions">
          {order.actions.filter((a) => a !== "decline").map((a) => (
            <button key={a} className="a-btn" disabled={busy} onClick={() => act(a)}>{ACTION_TITLES[a]}</button>
          ))}
          {order.actions.includes("decline") && !declining && (
            <button className="a-btn a-btn--danger-ghost" disabled={busy} onClick={() => setDeclining(true)}>Отклонить…</button>
          )}
        </div>
      )}
      {declining && (
        <div className="a-decline">
          <label className="a-field">
            <span className="a-field__label">Причина — её увидит покупатель</span>
            <textarea rows={3} maxLength={255} value={reason} onChange={(e) => setReason(e.target.value)} autoFocus />
          </label>
          <div className="a-details__actions">
            <button className="a-btn a-btn--danger" disabled={busy} onClick={() => act("decline")}>Отклонить заказ</button>
            <button className="a-btn a-btn--ghost" onClick={() => setDeclining(false)}>Отмена</button>
          </div>
        </div>
      )}
    </div>
  );
}
