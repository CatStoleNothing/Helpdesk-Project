import logging
from sqlalchemy import text, inspect
from models.db_init import SessionLocal

def migrate():
    """Добавляет поля active_from, active_to и is_active в таблицу positions"""
    logging.info("Начинаем миграцию для добавления полей активности в таблицу positions...")
    
    db = SessionLocal()
    try:
        # Проверяем существование колонок
        inspector = inspect(db.get_bind())
        columns = [col['name'] for col in inspector.get_columns('positions')]
        
        # Добавляем колонку active_from, если её нет
        if 'active_from' not in columns:
            db.execute(text("ALTER TABLE positions ADD COLUMN active_from DATE"))
            logging.info("Колонка active_from добавлена")
        
        # Добавляем колонку active_to, если её нет
        if 'active_to' not in columns:
            db.execute(text("ALTER TABLE positions ADD COLUMN active_to DATE"))
            logging.info("Колонка active_to добавлена")
        
        # Добавляем колонку is_active, если её нет
        if 'is_active' not in columns:
            db.execute(text("ALTER TABLE positions ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            logging.info("Колонка is_active добавлена")
        
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