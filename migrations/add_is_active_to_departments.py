import os
import sys
import logging

# Добавляем корневую директорию проекта в путь Python
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db_init import SessionLocal
from sqlalchemy import text

def migrate():
    """Добавляет поле is_active в таблицу departments"""
    logging.info("Начинаем миграцию для добавления поля is_active в таблицу departments...")
    
    db = SessionLocal()
    try:
        # Проверяем, существует ли уже колонка is_active
        result = db.execute(text("PRAGMA table_info(departments)"))
        columns = [row[1] for row in result]
        
        if 'is_active' not in columns:
            # Добавляем колонку is_active
            db.execute(text("ALTER TABLE departments ADD COLUMN is_active BOOLEAN DEFAULT 1"))
            
            # Обновляем существующие записи
            db.execute(text("UPDATE departments SET is_active = 1 WHERE is_active IS NULL"))
            
            db.commit()
            logging.info("Миграция успешно завершена")
        else:
            logging.info("Колонка is_active уже существует, миграция не требуется")
            
    except Exception as e:
        db.rollback()
        logging.error(f"Ошибка при выполнении миграции: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate() 