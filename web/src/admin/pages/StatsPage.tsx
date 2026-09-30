import { useState } from "react";

import { dateTime, rub } from "../../format";
import { adminApi } from "../api";
import type { Bucket } from "../types";
import { Card, Failure, Loading, useData } from "../ui";

const PERIODS = [
  { days: 7, title: "7 дней" },
  { days: 30, title: "30 дней" },
  { days: 90, title: "3 месяца" },
  { days: 365, title: "Год" },
  { days: null, title: "Всё время" },
];

function Tile({ title, bucket, tone }: { title: string; bucket: Bucket; tone: string }) {
  return (
    <div className={`a-tile a-tile--${tone}`}>
      <span className="a-tile__title">{title}</span>
      <b className="a-tile__value">{bucket.count}</b>
      <span className="a-muted">{rub(bucket.total)}</span>
    </div>
  );
}

export function StatsPage({ shopId }: { shopId: number | null }) {
  const [days, setDays] = useState<number | null>(30);
  const { data: stats, error, reload } = useData(() => adminApi.stats(days, shopId), [days, shopId]);

  return (
    <>
      <div className="a-toolbar">
        <div className="a-tabs" role="tablist">
          {PERIODS.map((p) => (
            <button key={p.title} role="tab" aria-selected={days === p.days} className={days === p.days ? "is-active" : ""}
              onClick={() => setDays(p.days)}>
              {p.title}
            </button>
          ))}
        </div>
      </div>
      {error ? <Failure message={error} onRetry={reload} /> : !stats ? <Loading /> : (
        <>
          <div className="a-tiles">
            <Tile title="Новые" bucket={stats.new} tone="new" />
            <Tile title="В работе" bucket={stats.in_progress} tone="work" />
            <Tile title="Выданы" bucket={stats.completed} tone="ready" />
            <Tile title="Отклонены" bucket={stats.declined} tone="declined" />
          </div>
          <Card title="Продажи по товарам (подтверждённые и выданные)">
            {stats.sales.length === 0 ? <div className="a-state">Продаж за период нет.</div> : (
              <table className="a-table">
                <thead><tr><th>Товар</th><th>Кг</th><th>Сумма</th></tr></thead>
                <tbody>
                  {stats.sales.map((s) => (
                    <tr key={s.name}><td>{s.name}</td><td>{Number(s.kg).toLocaleString("ru-RU")}</td><td>{rub(s.total)}</td></tr>
                  ))}
                </tbody>
                <tfoot>
                  <tr>
                    <th>Итого</th>
                    <th>{stats.sales.reduce((sum, s) => sum + Number(s.kg), 0).toLocaleString("ru-RU")}</th>
                    <th>{rub(stats.sales.reduce((sum, s) => sum + Number(s.total), 0))}</th>
                  </tr>
                </tfoot>
              </table>
            )}
          </Card>
          <Card title="Покупатели и дегустации">
            <dl className="a-dl">
              <dt>{shopId === null ? "Пользователей" : "Покупателей"}</dt><dd>{stats.customers}</dd>
              <dt>Ждут приглашения на дегустацию</dt><dd>{stats.tasting_waiting}</dd>
              {stats.next_tasting && (
                <>
                  <dt>Ближайшая дегустация</dt>
                  <dd>
                    {dateTime(stats.next_tasting.starts_at)} — приглашено {stats.next_tasting.invited},
                    придут {stats.next_tasting.going}, не смогут {stats.next_tasting.declined}
                  </dd>
                </>
              )}
            </dl>
          </Card>
        </>
      )}
    </>
  );
}
