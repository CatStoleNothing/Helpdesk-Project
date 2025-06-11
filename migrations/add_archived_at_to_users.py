import logging
from sqlalchemy import text, inspect
from models.db_init import SessionLocal

def migrate():
    logging.info("Начинаем миграцию для добавления поля archived_at в таблицу users...")
    db = SessionLocal()
    try:
        inspector = inspect(db.get_bind())
        columns = [col['name'] for col in inspector.get_columns('users')]
        if 'archived_at' not in columns:
            db.execute(text("ALTER TABLE users ADD COLUMN archived_at DATE"))
            logging.info("Колонка archived_at добавлена")
        db.commit()
        logging.info("Миграция успешно завершена")
    except Exception as e:
        db.rollback()
        logging.error(f"Ошибка при миграции: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate() 