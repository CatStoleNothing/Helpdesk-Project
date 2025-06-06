#!/usr/bin/env python3
"""
Скрипт для создания куратора SNA.
Chat ID можно передать первым позиционным аргументом,
пароль – через переменную окружения ``CURATOR_PASSWORD``
или аргумент ``--password=<PWD>``.
"""

import os
import sys
import logging
from dotenv import load_dotenv

# Настройка логгирования
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

# Загрузка переменных окружения
load_dotenv()

from models.db_init import init_db, SessionLocal
from models.user_models import User

def create_curator(chat_id=None, password=None):
    """Создание куратора SNA с указанным chat_id или значением по умолчанию.
    Пароль должен быть передан через аргумент или переменную окружения.
    """
    # Инициализация БД если еще не инициализирована
    init_db()

    # Если chat_id не передан, используем значение по умолчанию
    if chat_id is None:
        chat_id = "864823503"  # Значение по умолчанию

    # Получаем пароль из аргумента или переменной окружения
    if password is None:
        password = os.getenv("CURATOR_PASSWORD")

    if not password:
        logger.error(
            "Не указан пароль куратора. Передайте его через --password или \n"
            "переменную окружения CURATOR_PASSWORD"
        )
        return False

    user_db = SessionLocal()
    try:
        # Проверяем, существует ли уже пользователь SNA
        existing_user = user_db.query(User).filter(User.username == "SNA").first()

        if existing_user:
            logger.warning("Пользователь SNA уже существует в системе!")

            # Если пользователь существует, но chat_id отличается, предлагаем обновить
            if existing_user.chat_id != chat_id:
                logger.warning(f"У существующего пользователя SNA указан другой chat_id: {existing_user.chat_id}")
                logger.warning(f"Для обновления chat_id на {chat_id}, используйте параметр --force")

                # Если указан флаг --force, обновляем chat_id
                if "--force" in sys.argv:
                    old_chat_id = existing_user.chat_id
                    existing_user.chat_id = chat_id
                    user_db.commit()
                    logger.info(f"Chat ID пользователя SNA обновлен с {old_chat_id} на {chat_id}")

            return False

        # Проверяем, существует ли уже пользователь с таким chat_id
        existing_chat_id = user_db.query(User).filter(User.chat_id == chat_id).first()
        if existing_chat_id:
            logger.warning(f"Пользователь с chat_id {chat_id} уже существует: {existing_chat_id.full_name}")
            logger.warning("Укажите другой chat_id или удалите существующего пользователя.")
            return False

        # Создаем куратора

        curator = User(
            username="SNA",
            password_hash=User.get_password_hash(password),
            full_name="",
            position="",
            department="",
            office="",
            role="curator",  # Роль куратора
            is_confirmed=True,
            is_active=True,
            chat_id=chat_id
        )

        user_db.add(curator)
        user_db.commit()

        logger.info(
            f"Куратор SNA успешно создан с логином 'SNA' и chat_id '{chat_id}'"
        )
        logger.warning("ВНИМАНИЕ: Рекомендуется изменить стандартный пароль куратора!")
        return True

    except Exception as e:
        user_db.rollback()
        logger.error(f"Ошибка при создании куратора: {str(e)}")
        return False
    finally:
        user_db.close()

if __name__ == "__main__":
    logger.info("Запуск создания куратора...")

    # Получаем chat_id и пароль из аргументов
    chat_id = None
    password = None
    for arg in sys.argv[1:]:
        if arg.startswith("--password="):
            password = arg.split("=", 1)[1]
        elif not arg.startswith("--") and chat_id is None:
            chat_id = arg

    create_curator(chat_id, password)
    logger.info("Скрипт завершен.")
