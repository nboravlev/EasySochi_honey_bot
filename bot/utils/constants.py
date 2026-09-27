"""Бизнес-константы. Перечисления статусов и ролей — в domain/enums.py."""

APIARY_ADDRESS = "Красная Поляна, ул. Плотинная, д. 4"
APIARY_LOCATION = (43.672805, 40.200094)  # широта, долгота

MAX_PRODUCT_COUNT = 20        # банок одного товара в заказе
MAX_PRICE = 1_000_000         # ₽ за одну позицию
MAX_COMMENT_LENGTH = 255      # orders.customer_comment VARCHAR(255)
MAX_PRODUCT_NAME_LENGTH = 100
DRAFT_TTL_HOURS = 24          # брошенный черновик заказа закрывается через сутки
