import logging
from sqlalchemy import text, inspect
from models.db_init import SessionLocal

def migrate():
    logging.info("Начинаем миграцию для добавления полей подтверждения/отклонения в таблицу users...")
    
    db = SessionLocal()
    try:
        # Проверяем существующие колонки
        inspector = inspect(db.bind)
        columns = [col['name'] for col in inspector.get_columns('users')]
        
        # Добавляем новые колонки, если их нет
        if 'approved_by_id' not in columns:
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN approved_by_id INTEGER REFERENCES users(id)
            """))
            logging.info("Добавлена колонка approved_by_id")
        
        if 'approved_at' not in columns:
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN approved_at TIMESTAMP
            """))
            logging.info("Добавлена колонка approved_at")
        
        if 'rejected_by_id' not in columns:
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN rejected_by_id INTEGER REFERENCES users(id)
            """))
            logging.info("Добавлена колонка rejected_by_id")
        
        if 'rejected_at' not in columns:
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN rejected_at TIMESTAMP
            """))
            logging.info("Добавлена колонка rejected_at")
        
        if 'rejection_reason' not in columns:
            db.execute(text("""
                ALTER TABLE users 
                ADD COLUMN rejection_reason TEXT
            """))
            logging.info("Добавлена колонка rejection_reason")
        
        db.commit()
        logging.info("Миграция успешно завершена")
    except Exception as e:
        db.rollback()
        logging.error(f"Ошибка при выполнении миграции: {str(e)}")
        raise
    finally:
        db.close()

if __name__ == "__main__":
    migrate() 