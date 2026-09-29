import { useEffect, useState } from "react";

import { api } from "./api";
import { Loader, TabBar, type Tab } from "./components";
import { useBackButton, useLoad } from "./hooks";
import { CatalogScreen } from "./screens/CatalogScreen";
import { DoneScreen } from "./screens/DoneScreen";
import { OrdersScreen } from "./screens/OrdersScreen";
import { ProductScreen } from "./screens/ProductScreen";
import { insideTelegram, linkedProductId, webApp } from "./telegram";
import type { Order } from "./types";

type Screen =
  | { name: "catalog" }
  | { name: "orders" }
  | { name: "product"; productId: number }
  | { name: "done"; order: Order };

function initialStack(): Screen[] {
  const productId = linkedProductId(webApp?.initDataUnsafe.start_param);
  return productId ? [{ name: "catalog" }, { name: "product", productId }] : [{ name: "catalog" }];
}

export function App() {
  const catalog = useLoad(api.catalog);
  const config = useLoad(api.config);
  const [stack, setStack] = useState<Screen[]>(initialStack);
  const screen = stack[stack.length - 1];

  const push = (next: Screen) => setStack((s) => [...s, next]);
  const back = () => setStack((s) => (s.length > 1 ? s.slice(0, -1) : s));
  const open = (tab: Tab) => setStack([{ name: tab }]);

  useBackButton(stack.length > 1 ? back : null);
  useEffect(() => {
    // тело в скобках: в новых Chromium scrollTo возвращает Promise, а React принял бы его за функцию очистки
    window.scrollTo(0, 0);
  }, [screen]);

  let content;
  switch (screen.name) {
    case "catalog":
      content = (
        <CatalogScreen
          catalog={catalog.data}
          error={catalog.error}
          onRetry={catalog.retry}
          onOpen={(productId) => push({ name: "product", productId })}
        />
      );
      break;
    case "product": {
      const product = catalog.data?.products.find((p) => p.id === screen.productId);
      if (!catalog.data) content = <Loader />;
      else if (!product) content = <div className="state">Этот мёд уже не продаётся.</div>;
      else
        content = (
          <ProductScreen
            product={product}
            botUrl={config.data?.bot_url ?? null}
            onBack={back}
            onOrdered={(order) => {
              setStack([{ name: "catalog" }, { name: "done", order }]);
              catalog.retry();
            }}
          />
        );
      break;
    }
    case "orders":
      content = <OrdersScreen onCatalog={() => open("catalog")} />;
      break;
    case "done":
      content = <DoneScreen order={screen.order} onOrders={() => open("orders")} onCatalog={() => open("catalog")} />;
      break;
  }

  const tab = screen.name === "catalog" || screen.name === "orders" ? screen.name : null;
  return (
    <div className={insideTelegram && tab ? "app app--tabs" : "app"}>
      <main>{content}</main>
      {insideTelegram && tab && <TabBar active={tab} onSelect={open} />}
    </div>
  );
}
