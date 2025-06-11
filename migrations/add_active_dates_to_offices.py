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
    """Добавляет поля active_from, active_to и is_active в таблицу offices"""
    session = SessionLocal()
    try:
        # Проверяем, существует ли колонка active_from
        result = session.execute(text("""
            SELECT COUNT(*) 
            FROM pragma_table_info('offices') 
            WHERE name = 'active_from'
        """))
        if result.scalar() == 0:
            logger.info("Добавляем колонки active_from, active_to и is_active в таблицу offices")
            
            # Добавляем колонку active_from
            session.execute(text("""
                ALTER TABLE offices 
                ADD COLUMN active_from DATE
            """))
            
            # Добавляем колонку active_to
            session.execute(text("""
                ALTER TABLE offices 
                ADD COLUMN active_to DATE
            """))
            
            # Добавляем колонку is_active
            session.execute(text("""
                ALTER TABLE offices 
                ADD COLUMN is_active BOOLEAN DEFAULT 1
            """))
            
            session.commit()
            logger.info("Колонки успешно добавлены")
        else:
            logger.info("Колонки уже существуют")
    except Exception as e:
        logger.error(f"Ошибка при миграции: {str(e)}")
        session.rollback()
        raise
    finally:
        session.close()

if __name__ == "__main__":
    migrate() 