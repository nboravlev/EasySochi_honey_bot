import { useState } from "react";

import { rub, sizeLabel } from "../../format";
import { adminApi } from "../api";
import type { AdminMe, AdminProduct, AdminShop, ProductState, Reference } from "../types";
import { Badge, Card, Failure, Field, Loading, useAction, useData } from "../ui";

const STATE: Record<ProductState, { title: string; tone: string }> = {
  published: { title: "В продаже", tone: "ready" },
  draft: { title: "Черновик", tone: "new" },
  withdrawn: { title: "Снят", tone: "done" },
};

export function ProductsPage({ me, shopId, shops }: { me: AdminMe; shopId: number | null; shops: AdminShop[] }) {
  const products = useData(() => adminApi.products(shopId), [shopId]);
  const reference = useData(() => adminApi.reference(), []);
  const [editing, setEditing] = useState<AdminProduct | "new" | null>(null);

  if (products.error) return <Failure message={products.error} onRetry={products.reload} />;
  if (!products.data || !reference.data) return <Loading />;

  const saved = (product: AdminProduct) => {
    products.setData((list) => {
      const rest = (list ?? []).filter((p) => p.id !== product.id);
      return [product, ...rest];
    });
    setEditing(product);
  };

  if (editing) {
    return (
      <ProductEditor
        product={editing === "new" ? null : editing}
        reference={reference.data}
        me={me}
        shops={shops}
        defaultShopId={shopId}
        onSaved={saved}
        onClose={() => setEditing(null)}
        onTypeAdded={reference.reload}
      />
    );
  }

  return (
    <Card title="Товары" actions={<button className="a-btn" onClick={() => setEditing("new")}>＋ Новый товар</button>}>
      {products.data.length === 0 ? (
        <div className="a-state">Товаров пока нет.</div>
      ) : (
        <ul className="a-products">
          {products.data.map((p) => {
            const prices = p.offers.filter((o) => o.active);
            return (
              <li key={p.id}>
                <button className="a-product" onClick={() => setEditing(p)}>
                  {p.photos[0]?.url ? <img src={p.photos[0].url} alt="" /> : <span className="a-product__nophoto">🍯</span>}
                  <span className="a-product__body">
                    <b>{p.name}</b>
                    <span className="a-muted">{p.type.name}{shopId === null && me.is_owner ? ` · ${p.shop.name}` : ""}</span>
                    <span>{prices.map((o) => `${sizeLabel(o.kg)} — ${rub(o.price)}`).join(", ") || "нет цен"}</span>
                  </span>
                  <Badge tone={STATE[p.state].tone}>{STATE[p.state].title}</Badge>
                </button>
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}

interface EditorProps {
  product: AdminProduct | null;
  reference: Reference;
  me: AdminMe;
  shops: AdminShop[];
  defaultShopId: number | null;
  onSaved: (p: AdminProduct) => void;
  onClose: () => void;
  onTypeAdded: () => void;
}

interface OfferDraft {
  active: boolean;
  price: string;
}

function ProductEditor({ product, reference, me, shops, defaultShopId, onSaved, onClose, onTypeAdded }: EditorProps) {
  const { busy, run } = useAction();
  const [name, setName] = useState(product?.name ?? "");
  const [typeId, setTypeId] = useState<number>(product?.type.id ?? reference.types[0]?.id ?? 0);
  const [description, setDescription] = useState(product?.description ?? "");
  const [shopId, setShopId] = useState<number | null>(product?.shop.id ?? defaultShopId ?? shops[0]?.id ?? null);
  const [offers, setOffers] = useState<Record<number, OfferDraft>>(() =>
    Object.fromEntries(reference.sizes.map((s) => {
      const existing = product?.offers.find((o) => o.size_id === s.id);
      return [s.id, { active: existing?.active ?? false, price: existing ? String(Number(existing.price)) : "" }];
    })),
  );
  const [newType, setNewType] = useState("");

  const offerList = () =>
    reference.sizes
      .filter((s) => offers[s.id].active || (product && offers[s.id].price))
      .map((s) => ({ size_id: s.id, price: offers[s.id].price.replace(",", "."), active: offers[s.id].active }));

  const save = async () => {
    if (!product) {
      const created = await run(() => adminApi.createProduct({
        shop_id: me.is_owner ? shopId : null, name, type_id: typeId, description,
        offers: offerList().filter((o) => o.active).map(({ size_id, price }) => ({ size_id, price })),
      }), "Черновик создан. Добавьте фото и выставьте в продажу.");
      if (created) onSaved(created);
      return;
    }
    const updated = await run(async () => {
      await adminApi.updateProduct(product.id, { name, type_id: typeId, description });
      return adminApi.setOffers(product.id, offerList());
    }, "Сохранено.");
    if (updated) onSaved(updated);
  };

  const addType = async () => {
    const created = await run(() => adminApi.createType(newType.trim()), "Сорт добавлен.");
    if (created) {
      setTypeId(created.id);
      setNewType("");
      onTypeAdded();
    }
  };

  const upload = async (files: FileList | null) => {
    if (!product || !files) return;
    for (const file of Array.from(files)) {
      const updated = await run(() => adminApi.uploadPhoto(product.id, file));
      if (updated) onSaved(updated);
    }
  };

  const change = async (action: () => Promise<AdminProduct>, message: string) => {
    const updated = await run(action, message);
    if (updated) onSaved(updated);
  };

  return (
    <Card
      title={product ? product.name : "Новый товар"}
      actions={<button className="a-btn a-btn--ghost" onClick={onClose}>← К списку</button>}
    >
      {product && <p><Badge tone={STATE[product.state].tone}>{STATE[product.state].title}</Badge></p>}
      <div className="a-form">
        {me.is_owner && !product && (
          <Field label="Магазин">
            <select value={shopId ?? ""} onChange={(e) => setShopId(Number(e.target.value))}>
              {shops.map((s) => <option key={s.id} value={s.id}>{s.name}</option>)}
            </select>
          </Field>
        )}
        <Field label="Название">
          <input value={name} maxLength={100} onChange={(e) => setName(e.target.value)} />
        </Field>
        <Field label="Сорт">
          <select value={typeId} onChange={(e) => setTypeId(Number(e.target.value))}>
            {reference.types.map((t) => <option key={t.id} value={t.id}>{t.name}</option>)}
          </select>
        </Field>
        {me.is_owner && (
          <div className="a-inline">
            <input placeholder="Новый сорт" value={newType} maxLength={50} onChange={(e) => setNewType(e.target.value)} />
            <button className="a-btn a-btn--ghost" disabled={busy || !newType.trim()} onClick={addType}>Добавить сорт</button>
          </div>
        )}
        <Field label="Описание">
          <textarea rows={4} maxLength={2000} value={description} onChange={(e) => setDescription(e.target.value)} />
        </Field>

        <fieldset className="a-offers">
          <legend>Цены по размерам</legend>
          {reference.sizes.map((s) => (
            <div key={s.id} className="a-offer">
              <label>
                <input type="checkbox" checked={offers[s.id].active}
                  onChange={(e) => setOffers((o) => ({ ...o, [s.id]: { ...o[s.id], active: e.target.checked } }))} />
                {sizeLabel(s.kg)}{s.package ? <span className="a-muted"> · {s.package}</span> : null}
              </label>
              <input inputMode="decimal" placeholder="цена, ₽" value={offers[s.id].price} disabled={!offers[s.id].active}
                onChange={(e) => setOffers((o) => ({ ...o, [s.id]: { ...o[s.id], price: e.target.value } }))} />
            </div>
          ))}
        </fieldset>

        <div className="a-form__actions">
          <button className="a-btn" disabled={busy || !name.trim()} onClick={save}>
            {product ? "Сохранить" : "Создать черновик"}
          </button>
          {product && product.state !== "published" && (
            <button className="a-btn a-btn--ok" disabled={busy}
              onClick={() => change(() => adminApi.publish(product.id), "Товар в продаже.")}>
              {product.state === "draft" ? "Выставить в продажу" : "Вернуть в продажу"}
            </button>
          )}
          {product && product.state === "published" && (
            <button className="a-btn a-btn--danger-ghost" disabled={busy}
              onClick={() => change(() => adminApi.withdraw(product.id), "Товар снят с продажи.")}>
              Снять с продажи
            </button>
          )}
        </div>
      </div>

      {product && (
        <div className="a-photos">
          <h3>Фото</h3>
          <div className="a-photos__grid">
            {product.photos.map((p) => (
              <figure key={p.id}>
                {p.url ? <img src={p.url} alt="" /> : <span className="a-product__nophoto">🍯</span>}
                <button className="a-icon" aria-label="Убрать фото" disabled={busy}
                  onClick={() => change(() => adminApi.removePhoto(product.id, p.id), "Фото убрано.")}>✕</button>
              </figure>
            ))}
            <label className="a-upload">
              <input type="file" accept="image/*" multiple disabled={busy} onChange={(e) => { void upload(e.target.files); e.target.value = ""; }} />
              <span>＋ Загрузить</span>
            </label>
          </div>
          <p className="a-muted">Фото обрезаются до квадрата по центру. Первое — обложка.</p>
        </div>
      )}
    </Card>
  );
}
