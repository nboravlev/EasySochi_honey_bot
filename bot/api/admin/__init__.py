"""API админки (/api/admin): заказы, товары, магазины и менеджеры, статистика, очередь уведомлений.

Вход — api.admin.deps (Telegram Mini App или сессия из ссылки бота); права — как в боте.
"""
from fastapi import APIRouter

from api.admin import auth, monitoring, orders, products, shops

router = APIRouter(prefix="/api/admin")
for module in (auth, orders, products, shops, monitoring):
    router.include_router(module.router)
