import os
import psycopg2
from psycopg2 import sql
from dotenv import load_dotenv

# Загружаем переменные из .env
load_dotenv()

# Подтягиваем параметры из окружения
# Если переменной нет в .env, будет использовано значение по умолчанию (второй аргумент)
DB_HOST = os.getenv("SERVER_IP", "127.0.0.1") 
DB_PORT = os.getenv("POSTGRES_PORT", "5335")
DB_NAME = os.getenv("POSTGRES_DB")
DB_USER = os.getenv("POSTGRES_USER")
DB_PASSWORD = os.getenv("POSTGRES_PASSWORD")
SCHEMA = "public"

def synchronize_sequences():
    conn = psycopg2.connect(
        host=DB_HOST,
        port=DB_PORT,
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD
    )
    conn.autocommit = True
    cur = conn.cursor()

    # Получаем все таблицы в схеме
    cur.execute(
        sql.SQL("""
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = %s AND table_type='BASE TABLE';
        """),
        [SCHEMA]
    )
    tables = [row[0] for row in cur.fetchall()]

    for table in tables:
        # Получаем все serial / bigserial колонки с их последовательностями
        cur.execute(
            sql.SQL("""
                SELECT
                    a.attname AS column_name,
                    seq.relname AS sequence_name
                FROM pg_class AS tbl
                JOIN pg_attribute AS a
                    ON a.attrelid = tbl.oid
                JOIN pg_attrdef AS ad
                    ON ad.adrelid = tbl.oid AND ad.adnum = a.attnum
                JOIN pg_class AS seq
                    ON seq.oid = substring(pg_get_expr(ad.adbin, ad.adrelid)
                                            from 'nextval\\(''([^'']+)''::regclass')::regclass
                WHERE tbl.relname = %s
                    AND a.attnum > 0
                    AND NOT a.attisdropped;
            """),
            [table]
        )
        columns = cur.fetchall()

        for column_name, sequence_name in columns:
            # Получаем максимальный id
            cur.execute(
                sql.SQL("SELECT COALESCE(MAX({column}), 0) FROM {table}")
                .format(column=sql.Identifier(column_name),
                        table=sql.Identifier(table))
            )
            max_id = cur.fetchone()[0]

            if max_id == 0:
                print(f"⚠️  Table {table}, column {column_name} is empty, sequence {sequence_name} not updated.")
                continue

            # Устанавливаем счётчик
            cur.execute(
                sql.SQL("SELECT setval(%s, %s, true)"),
                [sequence_name, max_id]
            )

            print(f"✅ {table}.{column_name}: sequence '{sequence_name}' → {max_id}")

    cur.close()
    conn.close()
    print("\n🎯 Синхронизация всех sequence завершена.")

if __name__ == "__main__":
    synchronize_sequences()