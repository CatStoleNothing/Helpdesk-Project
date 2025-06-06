import logging
from models.ticket_models import TicketCategory
from models.db_init import SessionLocal

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def init_categories():
    """
    Инициализация базы данных начальными категориями заявок
    """
    # Список начальных категорий
    default_categories = [
        {
            "name": "МИС",
            "description": "Вопросы, связанные с медицинской информационной системой"
        },
        {
            "name": "ЛИС",
            "description": "Вопросы, связанные с лабораторной информационной системой"
        },
        {
            "name": "Технические проблемы",
            "description": "Технические неисправности компьютеров, принтеров, сети и т.д."
        },
        {
            "name": "Предложения",
            "description": "Предложения по улучшению работы систем и сервисов"
        }
    ]

    try:
        ticket_db = SessionLocal()

        # Проверяем существующие категории
        existing_categories = ticket_db.query(TicketCategory).all()
        existing_names = [cat.name for cat in existing_categories]

        # Добавляем отсутствующие категории
        for category_data in default_categories:
            if category_data["name"] not in existing_names:
                new_category = TicketCategory(
                    name=category_data["name"],
                    description=category_data["description"]
                )
                ticket_db.add(new_category)
                logger.info(f"Категория '{category_data['name']}' добавлена.")
            else:
                logger.info(f"Категория '{category_data['name']}' уже существует.")

        ticket_db.commit()
        logger.info("Инициализация категорий завершена успешно.")
    except Exception as e:
        logger.error(f"Ошибка при инициализации категорий: {str(e)}")
        ticket_db.rollback()
    finally:
        ticket_db.close()

if __name__ == "__main__":
    logger.info("Начало инициализации категорий...")
    init_categories()
