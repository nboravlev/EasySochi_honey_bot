import { useState } from "react";

import { ErrorBox, Loader, Photo, Section } from "../components";
import { mapUrl, minPrice, rub } from "../format";
import { openExternal } from "../telegram";
import type { Catalog, Product } from "../types";

interface Props {
  catalog: Catalog | null;
  error: string | null;
  onRetry: () => void;
  onOpen: (productId: number) => void;
}

export function CatalogScreen({ catalog, error, onRetry, onOpen }: Props) {
  const [typeId, setTypeId] = useState<number | null>(null);

  if (error) return <ErrorBox message={error} onRetry={onRetry} />;
  if (!catalog) return <Loader />;

  const products = typeId === null ? catalog.products : catalog.products.filter((p) => p.type.id === typeId);
  const title = catalog.shop?.name ?? "Мёд от пасечников";

  return (
    <>
      <header className="hero">
        <h1>{title}</h1>
        <p>Горный мёд с пасеки. Самовывоз, оплата при получении.</p>
      </header>

      {catalog.types.length > 1 && (
        <div className="chips" role="tablist" aria-label="Сорта">
          <button className={typeId === null ? "chip is-active" : "chip"} onClick={() => setTypeId(null)}>
            Все
          </button>
          {catalog.types.map((t) => (
            <button key={t.id} className={typeId === t.id ? "chip is-active" : "chip"} onClick={() => setTypeId(t.id)}>
              {t.name}
            </button>
          ))}
        </div>
      )}

      {products.length === 0 ? (
        <div className="state">Сейчас мёда в продаже нет — загляните позже 🐝</div>
      ) : (
        <div className="grid">
          {products.map((p) => (
            <ProductCard key={p.id} product={p} showShop={!catalog.shop} onOpen={() => onOpen(p.id)} />
          ))}
        </div>
      )}

      {catalog.shop && (
        <Section title="Где забрать">
          {catalog.shop.locations.map((loc) => {
            const map = mapUrl(loc);
            return (
              <div key={loc.id} className="place">
                <div>
                  <b>{loc.name}</b>
                  <div>{loc.address}</div>
                  {loc.opening_hours && <div className="muted">{loc.opening_hours}</div>}
                </div>
                {map && (
                  <button className="button button--secondary" onClick={() => openExternal(map)}>
                    На карте
                  </button>
                )}
              </div>
            );
          })}
          {catalog.shop.phone && (
            <a className="link" href={`tel:${catalog.shop.phone.replace(/[^\d+]/g, "")}`}>
              ☎️ {catalog.shop.phone}
            </a>
          )}
        </Section>
      )}
    </>
  );
}

function ProductCard({ product, showShop, onOpen }: { product: Product; showShop: boolean; onOpen: () => void }) {
  const from = minPrice(product);
  return (
    <button className="card" onClick={onOpen}>
      <Photo src={product.photos[0]} alt={product.name} className="card__photo" />
      <div className="card__body">
        <div className="card__name">{product.name}</div>
        <div className="muted">{showShop ? `${product.type.name} · ${product.shop.name}` : product.type.name}</div>
        {from && <div className="card__price">от {rub(from)}</div>}
      </div>
    </button>
  );
}
