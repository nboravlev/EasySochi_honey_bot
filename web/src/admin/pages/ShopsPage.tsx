import { useState } from "react";

import { ApiError } from "../../api";
import { adminApi } from "../api";
import type { AdminLocation, AdminMe, AdminShop, Manager } from "../types";
import { Badge, Card, Failure, Field, Loading, useAction, useData } from "../ui";

type LocationDraft = Omit<AdminLocation, "id">;

const EMPTY_LOCATION: LocationDraft = {
  name: "", address: "", latitude: null, longitude: null, opening_hours: null, is_pickup: true, is_active: true,
};

export function ShopsPage({ me, shops, onShopsChanged }: { me: AdminMe; shops: AdminShop[]; onShopsChanged: () => void }) {
  return (
    <>
      {shops.map((shop) => <ShopCard key={shop.id} shop={shop} editable={me.is_owner} onChanged={onShopsChanged} />)}
      {me.is_owner && <NewShop onCreated={onShopsChanged} />}
      {me.is_owner && <Managers shops={shops} onChanged={onShopsChanged} />}
      {!me.is_owner && <p className="a-muted">Изменить данные магазина может владелец платформы.</p>}
    </>
  );
}

function ShopCard({ shop, editable, onChanged }: { shop: AdminShop; editable: boolean; onChanged: () => void }) {
  const { busy, run } = useAction();
  const [name, setName] = useState(shop.name);
  const [phone, setPhone] = useState(shop.phone ?? "");
  const [chat, setChat] = useState(shop.staff_chat_id ?? "");
  const [editing, setEditing] = useState<number | "new" | null>(null);

  const saveShop = async () => {
    const done = await run(async () => {
      await adminApi.updateShop(shop.id, { name, phone });
      const chatId = chat.trim() ? Number(chat.trim()) : null;
      if (chatId !== null && !Number.isInteger(chatId)) throw new ApiError(0, "ID чата — целое число, например -1001234567890.");
      if (String(chatId ?? "") !== (shop.staff_chat_id ?? "")) await adminApi.setStaffChat(shop.id, chatId);
      return true;
    }, "Магазин сохранён.");
    if (done) onChanged();
  };
  const toggle = async () => {
    if (await run(() => adminApi.updateShop(shop.id, { is_active: !shop.is_active }))) onChanged();
  };

  return (
    <Card
      title={<>{shop.name} {shop.is_storefront && <Badge tone="ready">витрина</Badge>} {!shop.is_active && <Badge tone="declined">выключен</Badge>}</>}
      actions={<span className="a-muted">{shop.slug} · менеджеров: {shop.managers}</span>}
    >
      <div className="a-form a-form--grid">
        <Field label="Название"><input value={name} disabled={!editable} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Телефон для покупателей"><input value={phone} disabled={!editable} onChange={(e) => setPhone(e.target.value)} /></Field>
        <Field label="Служебный Telegram-чат (ID группы)" hint="Туда приходят новые заказы. Бот должен быть в группе.">
          <input value={chat} disabled={!editable} placeholder="-1001234567890" onChange={(e) => setChat(e.target.value)} />
        </Field>
      </div>
      {editable && (
        <div className="a-form__actions">
          <button className="a-btn" disabled={busy} onClick={saveShop}>Сохранить</button>
          {!shop.is_storefront && (
            <button className="a-btn a-btn--ghost" disabled={busy} onClick={toggle}>{shop.is_active ? "Выключить" : "Включить"}</button>
          )}
        </div>
      )}

      <h3>Точки выдачи</h3>
      <ul className="a-locations">
        {shop.locations.map((loc) => (
          <li key={loc.id}>
            {editing === loc.id ? (
              <LocationForm initial={loc} busy={busy} onCancel={() => setEditing(null)} onSave={async (data) => {
                if (await run(() => adminApi.updateLocation(loc.id, data), "Точка сохранена.")) { setEditing(null); onChanged(); }
              }} />
            ) : (
              <div className="a-location">
                <div>
                  <b>{loc.name}</b> {!loc.is_active && <Badge tone="declined">выключена</Badge>} {!loc.is_pickup && <Badge tone="done">не для выдачи</Badge>}
                  <div>{loc.address}</div>
                  <div className="a-muted">
                    {loc.latitude != null ? `${loc.latitude.toFixed(5)}, ${loc.longitude?.toFixed(5)}` : "без координат"}
                    {loc.opening_hours ? ` · ${loc.opening_hours}` : ""}
                  </div>
                </div>
                {editable && <button className="a-btn a-btn--ghost" onClick={() => setEditing(loc.id)}>Изменить</button>}
              </div>
            )}
          </li>
        ))}
      </ul>
      {editable && (editing === "new" ? (
        <LocationForm initial={EMPTY_LOCATION} busy={busy} onCancel={() => setEditing(null)} onSave={async (data) => {
          if (await run(() => adminApi.addLocation(shop.id, data), "Точка добавлена.")) { setEditing(null); onChanged(); }
        }} />
      ) : (
        <button className="a-btn a-btn--ghost" onClick={() => setEditing("new")}>＋ Точка выдачи</button>
      ))}
    </Card>
  );
}

function LocationForm({ initial, busy, onSave, onCancel }: {
  initial: LocationDraft; busy: boolean; onSave: (data: LocationDraft) => void; onCancel: () => void;
}) {
  const [data, setData] = useState<LocationDraft>(initial);
  const [coords, setCoords] = useState(
    initial.latitude != null && initial.longitude != null ? `${initial.latitude}, ${initial.longitude}` : "",
  );
  const set = (patch: Partial<LocationDraft>) => setData((d) => ({ ...d, ...patch }));
  const submit = () => {
    const [lat, lon] = coords.split(/[,;\s]+/).filter(Boolean).map((v) => Number(v.replace(",", ".")));
    const valid = Number.isFinite(lat) && Number.isFinite(lon);
    onSave({ ...data, latitude: valid ? lat : null, longitude: valid ? lon : null });
  };
  return (
    <div className="a-form a-form--grid a-location-form">
      <Field label="Название"><input value={data.name} onChange={(e) => set({ name: e.target.value })} /></Field>
      <Field label="Адрес"><input value={data.address} onChange={(e) => set({ address: e.target.value })} /></Field>
      <Field label="Координаты (широта, долгота)" hint="Из Яндекс Карт: правый клик по точке → скопировать координаты.">
        <input value={coords} placeholder="43.672805, 40.200094" onChange={(e) => setCoords(e.target.value)} />
      </Field>
      <Field label="Часы работы"><input value={data.opening_hours ?? ""} onChange={(e) => set({ opening_hours: e.target.value })} /></Field>
      <label className="a-check"><input type="checkbox" checked={data.is_pickup} onChange={(e) => set({ is_pickup: e.target.checked })} /> Выдача заказов</label>
      <label className="a-check"><input type="checkbox" checked={data.is_active} onChange={(e) => set({ is_active: e.target.checked })} /> Работает</label>
      <div className="a-form__actions">
        <button className="a-btn" disabled={busy || !data.name.trim() || !data.address.trim()} onClick={submit}>Сохранить</button>
        <button className="a-btn a-btn--ghost" onClick={onCancel}>Отмена</button>
      </div>
    </div>
  );
}

function NewShop({ onCreated }: { onCreated: () => void }) {
  const { busy, run } = useAction();
  const [slug, setSlug] = useState("");
  const [name, setName] = useState("");
  const [phone, setPhone] = useState("");
  const create = async () => {
    if (await run(() => adminApi.createShop({ slug: slug.trim(), name: name.trim(), phone: phone.trim() }), "Магазин создан.")) {
      setSlug(""); setName(""); setPhone("");
      onCreated();
    }
  };
  return (
    <Card title="Новый магазин">
      <div className="a-form a-form--grid">
        <Field label="Адрес (slug)" hint="Латиница, цифры и дефис: adler-honey"><input value={slug} onChange={(e) => setSlug(e.target.value.toLowerCase())} /></Field>
        <Field label="Название"><input value={name} onChange={(e) => setName(e.target.value)} /></Field>
        <Field label="Телефон"><input value={phone} onChange={(e) => setPhone(e.target.value)} /></Field>
      </div>
      <div className="a-form__actions">
        <button className="a-btn" disabled={busy || !slug || !name.trim()} onClick={create}>Создать</button>
      </div>
    </Card>
  );
}

function Managers({ shops, onChanged }: { shops: AdminShop[]; onChanged: () => void }) {
  const managers = useData(() => adminApi.managers(), []);
  const { busy, run } = useAction();
  const [who, setWho] = useState("");
  const [shopId, setShopId] = useState<number>(shops[0]?.id ?? 0);

  const add = async () => {
    if (await run(() => adminApi.addManager(who.trim(), shopId), "Менеджер назначен, ему пришло сообщение в Telegram.")) {
      setWho("");
      managers.reload();
      onChanged();
    }
  };
  const remove = async (m: Manager) => {
    if (!window.confirm(`Снять ${m.name ?? m.username ?? "менеджера"}? Он сразу потеряет доступ к админке и кнопкам в боте.`)) return;
    if ((await run(() => adminApi.removeManager(m.user_id), "Права сняты.")) !== undefined) {
      managers.reload();
      onChanged();
    }
  };

  return (
    <Card title="Менеджеры">
      {managers.error ? <Failure message={managers.error} onRetry={managers.reload} /> : !managers.data ? <Loading /> : (
        <table className="a-table">
          <thead><tr><th>Имя</th><th>Telegram</th><th>Магазин</th><th /></tr></thead>
          <tbody>
            {managers.data.map((m) => (
              <tr key={m.user_id}>
                <td>{m.name ?? "—"}</td>
                <td>{m.username ? `@${m.username}` : m.telegram_id ?? "—"}</td>
                <td>{m.shop?.name ?? "—"}</td>
                <td>{!m.is_owner && <button className="a-btn a-btn--danger-ghost" disabled={busy} onClick={() => remove(m)}>Снять</button>}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
      <div className="a-inline">
        <input placeholder="@username или Telegram ID" value={who} onChange={(e) => setWho(e.target.value)} />
        <select value={shopId} onChange={(e) => setShopId(Number(e.target.value))}>
          {shops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
        </select>
        <button className="a-btn" disabled={busy || who.trim().length < 2} onClick={add}>Назначить</button>
      </div>
      <p className="a-muted">Человек должен хотя бы раз нажать /start в боте.</p>
    </Card>
  );
}
