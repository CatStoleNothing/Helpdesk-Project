from sqlalchemy import create_engine, MetaData, inspect
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
import os
import logging

# Создаём единый движок для одной базы данных
engine = create_engine('sqlite:///helpdesk.db', connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

# Единая база моделей
Base = declarative_base()

# Функция инициализации базы данных
def init_db():
    if not os.path.exists("helpdesk.db"):
        logging.info("Файл helpdesk.db не найден, создаём новую базу данных")

    # Импортируем все модели, чтобы они зарегистрировались в Base
    from models.user_models import User  # Сначала импортируем User
    from models.ticket_models import (
        Ticket, Attachment, Message, TicketCategory, 
        AuditLog, DashboardMessage, DashboardAttachment
    )
    from models.department_models import Department
    from models.office_models import Office
    from models.position_models import Position

    # Создаём все таблицы
    Base.metadata.create_all(bind=engine)

    # Проверяем наличие таблицы audit_logs
    inspector = inspect(engine)
    if 'audit_logs' not in inspector.get_table_names():
        logging.warning("Таблица audit_logs не найдена в базе данных. Создаём её...")
        try:
            AuditLog.__table__.create(bind=engine)
            logging.info("Таблица audit_logs успешно создана через SQLAlchemy")
        except Exception as e:
            logging.error(f"Ошибка при создании таблицы audit_logs через SQLAlchemy: {str(e)}")
            try:
                with engine.connect() as conn:
                    conn.execute("""
                        CREATE TABLE IF NOT EXISTS audit_logs (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        actor_id VARCHAR(50) NOT NULL,
                        actor_name VARCHAR(100),
                        action_type VARCHAR(50) NOT NULL,
                        description TEXT NOT NULL,
                        entity_type VARCHAR(50),
                        entity_id VARCHAR(50),
                        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                        is_pdn_related BOOLEAN DEFAULT 0,
                        ip_address VARCHAR(50),
                        details TEXT
                        )
                    """)
                logging.info("Таблица audit_logs успешно создана через SQL")
            except Exception as sql_err:
                logging.error(f"Критическая ошибка при создании таблицы audit_logs: {str(sql_err)}")
    else:
        logging.info("Таблица audit_logs найдена в базе данных")

# Зависимость для получения сессии

def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
