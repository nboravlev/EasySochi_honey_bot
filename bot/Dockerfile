FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Корень проекта внутри контейнера — /bot
WORKDIR /bot

# Все зависимости ставятся из готовых колёс — компилятор и libpq не нужны
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Непривилегированный пользователь (UID 1000 — владелец томов на хосте).
# /app/state — файл состояния диалогов; том bot_state_honey при первом создании наследует владельца.
RUN useradd -m -u 1000 honeybot \
    && chmod +x /bot/entrypoint.sh \
    && mkdir -p /app/state \
    && chown -R honeybot:honeybot /bot /app/state
USER honeybot

ENTRYPOINT ["/bot/entrypoint.sh"]
CMD ["bot"]
