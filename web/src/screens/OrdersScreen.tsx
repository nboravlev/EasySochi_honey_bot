import { api } from "../api";
import { ErrorBox, Loader } from "../components";
import { dateTime, mapUrl, rub, sizeLabel, STATUS_TONE } from "../format";
import { useLoad } from "../hooks";
import { platform } from "../platform";
import type { Order } from "../types";

export function OrdersScreen({ onCatalog }: { onCatalog: () => void }) {
  const { data: orders, error, retry } = useLoad(api.orders);

  if (error) return <ErrorBox message={error} onRetry={retry} />;
  if (!orders) return <Loader />;

  return (
    <>
      <header className="hero hero--small">
        <h1>Мои заказы</h1>
        <button className="button button--secondary" onClick={retry}>
          Обновить
        </button>
      </header>
      {orders.length === 0 ? (
        <div className="state">
          <p>Заказов пока нет.</p>
          <button className="button" onClick={onCatalog}>
            В каталог
          </button>
        </div>
      ) : (
        <ul className="orders">
          {orders.map((order) => (
            <OrderCard key={order.id} order={order} />
          ))}
        </ul>
      )}
    </>
  );
}

export function OrderCard({ order }: { order: Order }) {
  const map = order.pickup ? mapUrl(order.pickup) : null;
  return (
    <li className="order">
      <div className="order__head">
        <span>
          №{order.id} · {dateTime(order.created_at)}
        </span>
        <span className={`badge badge--${STATUS_TONE[order.status.code]}`}>{order.status.title}</span>
      </div>
      <div className="order__line">
        {order.product_name} · {sizeLabel(order.size)} × {order.quantity}
      </div>
      <div className="order__total">{rub(order.total)}</div>
      {order.decline_reason && <div className="order__note">Причина: {order.decline_reason}</div>}
      {order.comment && <div className="muted">Комментарий: {order.comment}</div>}
      {order.pickup && (
        <div className="order__pickup">
          <span>📍 {order.pickup.address}</span>
          {map && (
            <button className="link" onClick={() => platform().openExternal(map)}>
              на карте
            </button>
          )}
        </div>
      )}
    </li>
  );
}
