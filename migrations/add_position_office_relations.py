from sqlalchemy import create_engine, MetaData, Table, Column, Integer, ForeignKey, inspect, text
import logging

def migrate():
    logging.info("Начинаем миграцию для добавления связей с должностями и кабинетами...")
    
    # Создаем подключение к базе данных
    engine = create_engine('sqlite:///helpdesk.db')
    metadata = MetaData()
    
    try:
        # Добавляем новые колонки
        with engine.connect() as conn:
            # Проверяем существование колонок
            inspector = inspect(engine)
            columns = [col['name'] for col in inspector.get_columns('users')]
            
            # Добавляем position_id если его нет
            if 'position_id' not in columns:
                conn.execute(text('ALTER TABLE users ADD COLUMN position_id INTEGER REFERENCES positions(id)'))
                logging.info("Добавлена колонка position_id")
            
            # Добавляем office_id если его нет
            if 'office_id' not in columns:
                conn.execute(text('ALTER TABLE users ADD COLUMN office_id INTEGER REFERENCES offices(id)'))
                logging.info("Добавлена колонка office_id")
            
            # Удаляем старые колонки если они есть
            if 'position' in columns:
                conn.execute(text('ALTER TABLE users DROP COLUMN position'))
                logging.info("Удалена старая колонка position")
            
            if 'department' in columns:
                conn.execute(text('ALTER TABLE users DROP COLUMN department'))
                logging.info("Удалена старая колонка department")
            
            if 'office' in columns:
                conn.execute(text('ALTER TABLE users DROP COLUMN office'))
                logging.info("Удалена старая колонка office")
            
            conn.commit()
            logging.info("Миграция успешно завершена")
            
    except Exception as e:
        logging.error(f"Ошибка при выполнении миграции: {str(e)}")
        raise 