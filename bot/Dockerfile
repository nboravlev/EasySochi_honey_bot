FROM python:3.12-slim

WORKDIR /bot 

# Корень проекта внутри контейнера — /bot

ENV PYTHONDONTWRITEBYTECODE 1
ENV PYTHONUNBUFFERED 1

# системные зависимости для psycopg2 и pg_isready

RUN apt-get update && \
    apt-get install -y --no-install-recommends gcc libpq-dev postgresql-client && \
    rm -rf /var/lib/apt/lists/*

COPY ./requirements.txt /bot/requirements.txt  
RUN pip install --no-cache-dir -r /bot/requirements.txt
  
# Устанавливаем зависимости

COPY . /bot/

RUN chmod +x /bot/entrypoint.sh  

# ENTRYPOINT прописан в образе
ENTRYPOINT ["/bot/entrypoint.sh"]

# CMD можно оставить универсальным
CMD ["bot"]

