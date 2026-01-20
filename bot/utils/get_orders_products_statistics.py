from sqlalchemy import select, func, and_
from sqlalchemy.orm import selectinload
from datetime import datetime, date
from decimal import Decimal
from db.models import Order, Product, ProductSize, Size, Session, User
from db.db_async import get_async_session

from utils.logging_config import (
    structured_logger, 
    log_db_select, 
    log_db_insert, 
    log_db_update,
    log_db_delete,
    LoggingContext,
    monitor_performance
)

import os

OWNER_ID = os.getenv("OWNER_ID")
if not (OWNER_ID):
    raise RuntimeError("Owner chat id did not set in environment variables")

ORDER_STATUS_CREATED = 1
ORDER_STATUS_CUSTOMER_INFORMED = 2
ORDER_STATUS_PROCESSING = 3
ORDER_STATUS_READY = 4
ORDER_STATUS_PAYED = 5 #продавец нажал на кнопку, когда отдал заказ
ORDER_STATUS_DECLINED = 6
ORDER_STATUS_EXPIRED = 7
ORDER_STATUS_DRAFT = 8

DEGUSTATION_ROLE = 3


@log_db_select(log_slow_only=True, slow_threshold=0.5)
async def get_manager_stats_message(user_tg_id: int) -> str:
    """
    Формирует сообщение со статистикой продаж и заказов для менеджера или админа.
    """
    async with get_async_session() as session:
        is_admin = str(user_tg_id) == str(OWNER_ID)

        # ===== 1. Продажи мёда по сортам =====
        stmt = (
            select(
                Product.name.label("product_name"),
                func.sum(Order.product_count * Size.name).label("total_kg"),
                func.sum(Order.total_price).label("total_sum")
            )
            .join(ProductSize, Order.product_size_id == ProductSize.id)
            .join(Product, ProductSize.product_id == Product.id)
            .join(Size, ProductSize.size_id == Size.id)
            .where(Order.status_id.in_([
                ORDER_STATUS_PAYED,
                ORDER_STATUS_PROCESSING,
                ORDER_STATUS_READY,
                ORDER_STATUS_CUSTOMER_INFORMED,
                ORDER_STATUS_CREATED

            ]))
            .group_by(Product.name)
            .order_by(func.sum(Order.product_count * Size.name).desc())  # <-- сортировка по количеству
        )

        if not is_admin:
            stmt = stmt.where(Product.created_by == user_tg_id)

        result = await session.execute(stmt)
        product_stats = result.all()

        # ===== 2. Общие итоги по заказам =====
        total_stmt = select(
            func.count(Order.id),
            func.sum(Order.total_price)
        )
        if not is_admin:
            total_stmt = (
                total_stmt.join(ProductSize, Order.product_size_id == ProductSize.id)
                          .join(Product, ProductSize.product_id == Product.id)
                          .where(Product.created_by == user_tg_id)
            )

        total_orders_count, total_orders_sum = (await session.execute(total_stmt)).one()

        # ===== 3. Подсчёт по статусам =====
        status_stmt = select(
            Order.status_id,
            func.count(Order.id),
            func.sum(Order.total_price)
        )
        if not is_admin:
            status_stmt = (
                status_stmt.join(ProductSize, Order.product_size_id == ProductSize.id)
                           .join(Product, ProductSize.product_id == Product.id)
                           .where(Product.created_by == user_tg_id)
            )
        status_stmt = status_stmt.group_by(Order.status_id)
        status_stats = {
            row[0]: {"count": row[1], "sum": row[2]}
            for row in (await session.execute(status_stmt)).all()
        }

        # ===== 4. Новые заказы (за сегодня) =====
#        today = date.today()
        new_orders_stmt = select(func.count(Order.id)).where(
#            func.date(Order.created_at) == today,
            Order.status_id == ORDER_STATUS_CREATED
        )
        if not is_admin:
            new_orders_stmt = (
                new_orders_stmt.join(ProductSize, Order.product_size_id == ProductSize.id)
                               .join(Product, ProductSize.product_id == Product.id)
                               .where(Product.created_by == user_tg_id)
            )

        new_orders = (await session.execute(new_orders_stmt)).scalar() or 0

        #======5.Записалось на дегустацию=====
        result = await session.execute(
            select(func.count(Session.tg_user_id)).where(
                Session.role_id == DEGUSTATION_ROLE,
                Session.sent_message == False
            )
        )
        user_count2test = result.scalar_one() or 0 # извлекаем число

        #=======всего пользователей =======
        result = await session.execute(
            select(func.count(User.id)).where(
                User.is_active == True
            )
        )
        user_count = result.scalar_one() or 0 # извлекаем число
    # ===== 6. Формирование текста =====
    header = "📊 <b>Общая статистика продаж</b>\n\n"

    # Блок мёда
    honey_text = "<b>🍯 статус продажи В работе и Завершено:</b>\n"
    total_kg = 0
    total_sum = 0
    for name, kg, summ in product_stats:
        honey_text += f"{name}: {kg or 0:.1f}кг | {summ or 0:.0f}₽\n"
        total_kg += kg or 0
        total_sum += summ or 0
    honey_text += f"\n<b>Итого:</b> {total_kg:.1f} кг | {total_sum:.0f}₽\n\n"

    completed_count = status_stats.get(ORDER_STATUS_PAYED, {}).get("count", 0)
    completed_sum = status_stats.get(ORDER_STATUS_PAYED, {}).get("sum", 0.0) or 0.0

    # Блок заказов
    in_progress_statuses = [ORDER_STATUS_PROCESSING,
                ORDER_STATUS_READY,
                ORDER_STATUS_CUSTOMER_INFORMED,
                ORDER_STATUS_CREATED]

    in_progress_count = sum(status_stats.get(s, {}).get("count", 0) for s in in_progress_statuses)
    in_progress_sum = sum(
    (status_stats.get(s, {}).get("sum") or Decimal(0))
    for s in in_progress_statuses
        )

    new_orders_sum = status_stats.get(ORDER_STATUS_CREATED, {}).get("sum", 0.0) or 0.0

    # --- текст ---
    orders_text = (
        f"📦 <b>Заказы</b> "
        f"Всего: {total_orders_count or 0} | {total_orders_sum or 0:.0f}₽\n"
        f"✅ Завершено: {completed_count} | {completed_sum:.0f}₽\n"
        f"🕓 В работе: {in_progress_count} | {in_progress_sum:.0f}₽\n "
        f"🚨 <b>Новые: {new_orders} | {new_orders_sum:.0f}₽</b>\n\n"
        f"👨 Пользователей: {user_count} <b>({user_count2test})</b>"
    )

    return header + honey_text + orders_text

