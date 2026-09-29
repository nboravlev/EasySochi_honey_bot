import { useEffect, useState } from "react";

import { api, ApiError } from "../api";
import { ErrorBox, Photo, Section } from "../components";
import { rub, sizeLabel } from "../format";
import { useMainButton } from "../hooks";
import { ensureWriteAccess, haptic, insideTelegram, openExternal } from "../telegram";
import type { Order, Product } from "../types";

const MAX_QUANTITY = 20; // как в боте (utils/constants.py)
const MAX_COMMENT = 255;

interface Props {
  product: Product;
  botUrl: string | null;
  onOrdered: (order: Order) => void;
  onBack: () => void;
}

export function ProductScreen({ product, botUrl, onOrdered, onBack }: Props) {
  const [offerId, setOfferId] = useState(product.offers[0]?.id);
  const [quantity, setQuantity] = useState(1);
  const [comment, setComment] = useState("");
  const [phone, setPhone] = useState("");
  const [savedPhone, setSavedPhone] = useState<string | null>(null);
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // телефон для связи: подставляем сохранённый (из бота или прошлого заказа)
  useEffect(() => {
    if (!insideTelegram) return;
    api
      .me()
      .then((me) => {
        setSavedPhone(me.phone);
        setPhone(me.phone ?? "");
      })
      .catch(() => undefined);
  }, []);

  const offer = product.offers.find((o) => o.id === offerId);
  const total = offer ? Number(offer.price) * quantity : 0;

  async function submit() {
    if (!offer || sending) return;
    setSending(true);
    setError(null);
    try {
      await ensureWriteAccess();
      if (phone.trim() !== (savedPhone ?? "")) {
        await api.updateMe({ phone: phone.trim() });
      }
      const order = await api.createOrder({ product_size_id: offer.id, quantity, comment: comment.trim() });
      haptic("success");
      onOrdered(order);
    } catch (e) {
      haptic("error");
      setError(e instanceof ApiError ? e.message : "Не удалось оформить заказ.");
    } finally {
      setSending(false);
    }
  }

  useMainButton(insideTelegram && offer ? `Заказать · ${rub(total)}` : null, submit, sending);

  return (
    <article className="product">
      {!insideTelegram && (
        <button className="back" onClick={onBack}>
          ← Каталог
        </button>
      )}

      <div className="gallery">
        {product.photos.length ? (
          product.photos.map((src, i) => <Photo key={src} src={src} alt={`${product.name}, фото ${i + 1}`} className="gallery__photo" />)
        ) : (
          <Photo alt={product.name} className="gallery__photo" />
        )}
      </div>

      <h1 className="product__name">{product.name}</h1>
      <div className="muted">
        {product.type.name} · {product.shop.name}
      </div>
      {product.description && <p className="product__description">{product.description}</p>}

      <Section title="Объём">
        <div className="options" role="radiogroup" aria-label="Объём">
          {product.offers.map((o) => (
            <label key={o.id} className={o.id === offerId ? "option is-active" : "option"}>
              <input type="radio" name="offer" checked={o.id === offerId} onChange={() => setOfferId(o.id)} />
              <span>{sizeLabel(o.size)}</span>
              <b>{rub(o.price)}</b>
            </label>
          ))}
        </div>
      </Section>

      {insideTelegram ? (
        <>
          <Section title="Количество">
            <div className="stepper">
              <button aria-label="Меньше" disabled={quantity <= 1} onClick={() => setQuantity((q) => q - 1)}>
                −
              </button>
              <span aria-live="polite">{quantity}</span>
              <button aria-label="Больше" disabled={quantity >= MAX_QUANTITY} onClick={() => setQuantity((q) => q + 1)}>
                +
              </button>
            </div>
          </Section>

          <Section title="Для продавца">
            <label className="field">
              <span>Телефон для связи (необязательно)</span>
              <input type="tel" inputMode="tel" maxLength={20} placeholder="+7 900 000-00-00" value={phone} onChange={(e) => setPhone(e.target.value)} />
            </label>
            <label className="field">
              <span>Комментарий к заказу</span>
              <textarea maxLength={MAX_COMMENT} rows={2} placeholder="Например, когда удобно забрать" value={comment} onChange={(e) => setComment(e.target.value)} />
            </label>
          </Section>

          <div className="total">
            Итого: <b>{rub(total)}</b>
            <div className="muted">Самовывоз, оплата при получении</div>
          </div>
          {error && <ErrorBox message={error} />}
        </>
      ) : (
        <Section>
          <p className="muted">Заказать мёд можно в нашем Telegram-боте — там же придут уведомления о заказе.</p>
          {botUrl && (
            <button className="button" onClick={() => openExternal(botUrl)}>
              Заказать в Telegram
            </button>
          )}
        </Section>
      )}
    </article>
  );
}
