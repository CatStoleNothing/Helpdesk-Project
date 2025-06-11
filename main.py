import threading
import logging
import sys
import os

from app import app
from bot.bot import run_bot
from models.ticket_models import TicketCategory
from models.db_init import init_db, SessionLocal
from models.user_models import User
from models.ticket_models import (
    Ticket, Attachment, Message, DashboardMessage,
    DashboardAttachment, AuditLog
)
from models.department_models import Department
from models.office_models import Office
from models.position_models import Position
from migrations.add_archived_at_to_users import migrate as migrate_archived_at
from migrations.add_approval_fields_to_users import migrate as migrate_approval_fields

# Настройка логирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Запуск миграции базы данных при старте
logger.info("Запускаем миграцию базы данных...")

def run_bot_thread():
    logger.info("Запускаем Telegram бота...")
    run_bot()

if __name__ == "__main__":
    # Инициализация базы данных
    init_db()
    
    # Запуск миграций
    from migrations.add_is_active_to_departments import migrate as migrate_departments
    from migrations.add_position_office_relations import migrate as migrate_positions
    from migrations.add_department_to_offices import migrate as migrate_offices
    from migrations.add_active_dates_to_offices import migrate as migrate_office_dates
    from migrations.add_active_dates_to_positions import migrate as migrate_position_dates
    migrate_archived_at()
    migrate_approval_fields()
    
    migrate_departments()
    migrate_positions()
    migrate_offices()
    migrate_office_dates()
    migrate_position_dates()
    
    # Запуск Telegram бота
    logging.info("Запускаем Telegram бота...")
    bot_thread = threading.Thread(target=run_bot)
    bot_thread.daemon = True
    bot_thread.start()
    logging.info("Бот запущен")

    # Запуск Flask приложения
    debug_mode = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)