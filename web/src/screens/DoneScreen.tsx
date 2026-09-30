import { platform } from "../platform";
import type { Order } from "../types";
import { OrderCard } from "./OrdersScreen";

export function DoneScreen({ order, onOrders, onCatalog }: { order: Order; onOrders: () => void; onCatalog: () => void }) {
  return (
    <div className="done">
      <div className="done__icon" aria-hidden="true">
        ✅
      </div>
      <h1>Заказ №{order.id} создан</h1>
      <p className="muted">{platform().notificationsHint}</p>
      <ul className="orders">
        <OrderCard order={order} />
      </ul>
      <div className="done__actions">
        <button className="button" onClick={onOrders}>
          Мои заказы
        </button>
        <button className="button button--secondary" onClick={onCatalog}>
          В каталог
        </button>
      </div>
    </div>
  );
}
