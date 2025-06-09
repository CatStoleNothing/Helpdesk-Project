import threading
import logging
import sys
import os

from app import app
from bot.bot import run_bot

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
    # Запуск бота в отдельном потоке
    bot_thread = threading.Thread(target=run_bot_thread)
    bot_thread.daemon = True
    bot_thread.start()
    logger.info("Бот запущен")

    # Запуск Flask приложения
    debug_mode = os.environ.get("DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)