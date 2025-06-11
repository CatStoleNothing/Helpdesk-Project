import os
import sys
import logging
from sqlalchemy import text

# Добавляем корневую директорию проекта в PYTHONPATH
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from models.db_init import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def migrate():
    """Добавляет поле department_id в таблицу offices"""
    session = SessionLocal()
    try:
        # Проверяем, существует ли колонка
        result = session.execute(text("""
            SELECT COUNT(*) 
            FROM pragma_table_info('offices') 
            WHERE name = 'department_id'
        """))
        if result.scalar() == 0:
            logger.info("Добавляем колонку department_id в таблицу offices")
            session.execute(text("""
                ALTER TABLE offices 
                ADD COLUMN department_id INTEGER 
                REFERENCES departments(id)
            """))
            session.commit()
            logger.info("Колонка department_id успешно добавлена")
        else:
            logger.info("Колонка department_id уже существует")
    except Exception as e:
        logger.error(f"Ошибка при миграции: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    migrate() 