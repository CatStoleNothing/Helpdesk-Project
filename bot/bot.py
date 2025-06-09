import logging
import os
import re
import nest_asyncio
import asyncio.exceptions
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandObject
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, CallbackQuery, InputFile, FSInputFile
from sqlalchemy.orm import Session
from typing import List, Optional
import sys
import datetime
import asyncio
from aiogram.exceptions import TelegramAPIError
import requests
from dotenv import load_dotenv
from models.db_init import SessionLocal

# Add parent directory to path to import the models
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from models.user_models import User
from models.ticket_models import Ticket, Attachment, Message, TicketCategory, AuditLog

# Load environment variables
load_dotenv()

# Apply nest_asyncio to allow nested asyncio operations
nest_asyncio.apply()

# Configure logging
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(name)s - %(message)s')

# Initialization flag
_DEPENDENCIES_LOADED = True

# Initialize bot and dispatcher
API_TOKEN = os.getenv("TELEGRAM_API_TOKEN", "")
bot = Bot(token=API_TOKEN)
storage = MemoryStorage()
dp = Dispatcher(storage=storage)

class RegistrationStates(StatesGroup):
    waiting_for_gdpr_consent = State()
    waiting_for_fullname = State()
    waiting_for_position = State()
    waiting_for_department = State()
    waiting_for_office = State()
    waiting_for_phone = State()
    waiting_for_email = State()

class TicketStates(StatesGroup):
    waiting_for_category = State()
    waiting_for_title = State()
    waiting_for_description = State()
    waiting_for_priority = State()
    waiting_for_attachments = State()
    collecting_attachments = State()

class TicketSelectStates(StatesGroup):
    waiting_for_ticket_id = State()
    pagination_data = State()

class ActiveTicketStates(StatesGroup):
    chatting = State()

# Helper function to check if user exists
def get_user_by_chat_id(chat_id: str, db: Session) -> Optional[User]:
    return db.query(User).filter(User.chat_id == str(chat_id)).first()

# Helper function to check user status
async def check_user_status(chat_id: str, db: Session):
    """
    Проверяет статус пользователя: существует ли, активен ли, подтвержден ли.

    Args:
        chat_id: ID чата пользователя
        db: Сессия базы данных

    Returns:
        tuple: (status: bool, message: str | None, user: User | None)
            - status - True если все проверки пройдены, False если нет
            - message - сообщение об ошибке или None если проверки пройдены
            - user - объект пользователя или None если пользователь не найден
    """
    # Проверяем существование пользователя
    user = get_user_by_chat_id(chat_id, db)
    if not user:
        return False, "Вы не зарегистрированы в системе. Используйте /start для регистрации.", None

    # Проверяем активность аккаунта
    if not user.is_active:
        return False, "❌ Ваш аккаунт заблокирован. Обратитесь к администратору системы для выяснения причин.", user

    # Проверяем подтверждение администратором
    if not user.is_confirmed:
        return False, "⚠️ Ваш аккаунт ожидает подтверждения администратором.\n\nНекоторые функции ограничены до проверки. Используйте /profile для просмотра статуса.", user

    # Все проверки пройдены
    return True, None, user

# Функция для отправки уведомлений (синхронная)
def sync_send_notification(chat_id, message):
    if not chat_id:
        logging.error(f"Невозможно отправить сообщение: chat_id отсутствует")
        return False

    # Check for manually created users
    if isinstance(chat_id, str) and chat_id.startswith('manual_'):
        logging.warning(f"Попытка отправки сообщения вручную созданному пользователю: {chat_id}")
        return False

    # Ensure chat_id is a string
    chat_id_str = str(chat_id).strip()
    logging.info(f"Отправка сообщения пользователю {chat_id_str}: {message[:50]}...")

    # Prepare the API request
    api_url = f"https://api.telegram.org/bot{API_TOKEN}/sendMessage"

    try:
        # First attempt with original message
        payload = {
            'chat_id': chat_id_str,
            'text': message,
            'parse_mode': 'HTML'
        }

        response = requests.post(api_url, json=payload, timeout=10)

        if response.status_code == 200:
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str}")
            return True

        # If HTML parsing fails, try without HTML
        logging.warning(f"Ошибка при отправке сообщения: {response.text}. Пробуем без парсинга HTML...")
        clean_message = re.sub(r'<[^>]*>', '', message)

        payload = {
            'chat_id': chat_id_str,
            'text': clean_message
        }

        response = requests.post(api_url, json=payload, timeout=10)

        if response.status_code == 200:
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
            return True
        else:
            error_data = response.json() if response.content else {"description": "Unknown error"}
            logging.error(f"Не удалось отправить сообщение: {error_data.get('description', 'Unknown error')}")
            return False

    except Exception as e:
        logging.error(f"Ошибка отправки уведомления пользователю {chat_id}: {str(e)}")
        try:
            error_type = type(e).__name__
            logging.error(f"Тип ошибки: {error_type}")

            if hasattr(e, '__traceback__'):
                import traceback
                error_trace = ''.join(traceback.format_tb(e.__traceback__))
                logging.error(f"Трассировка: {error_trace}")
        except:
            pass

        return False

# Synchronous function to send a photo through the Telegram API
def sync_send_photo(chat_id, photo_path, caption=None):
    """
    Отправка фото пользователю через Telegram API

    Args:
        chat_id: ID чата пользователя
        photo_path: Путь к файлу изображения
        caption: Подпись к фото (опционально)

    Returns:
        bool: True если фото успешно отправлено, False в случае ошибки
    """
    if not chat_id:
        logging.error(f"Невозможно отправить фото: chat_id отсутствует")
        return False

    # Check for manually created users
    if isinstance(chat_id, str) and chat_id.startswith('manual_'):
        logging.warning(f"Попытка отправки фото вручную созданному пользователю: {chat_id}")
        return False

    # Ensure chat_id is a string
    chat_id_str = str(chat_id).strip()
    logging.info(f"Отправка фото пользователю {chat_id_str}")

    if not API_TOKEN:
        logging.error("Telegram bot token is not configured")
        return False

    try:
        # Prepare API URL for sendPhoto
        api_url = f"https://api.telegram.org/bot{API_TOKEN}/sendPhoto"

        # Prepare request data
        files = {'photo': open(photo_path, 'rb')}
        data = {'chat_id': chat_id_str}

        # Add caption if provided
        if caption:
            data['caption'] = caption
            data['parse_mode'] = 'HTML'

        # Send the request
        response = requests.post(api_url, files=files, data=data, timeout=30)

        if response.status_code == 200:
            logging.info(f"Фото успешно отправлено пользователю {chat_id_str}")
            return True
        else:
            error_data = response.json() if response.content else {"description": "Unknown error"}
            logging.error(f"Не удалось отправить фото: {error_data.get('description', 'Unknown error')}")
            return False

    except Exception as e:
        logging.error(f"Ошибка при отправке фото пользователю {chat_id}: {str(e)}")
        if hasattr(e, '__traceback__'):
            import traceback
            error_trace = ''.join(traceback.format_tb(e.__traceback__))
            logging.error(f"Трассировка: {error_trace}")
        return False

# Synchronous function to send a document through the Telegram API
def sync_send_document(chat_id, document_path, caption=None, original_filename=None):
    """
    Отправка документа пользователю через Telegram API
    """
    if not chat_id:
        logging.error(f"Невозможно отправить документ: chat_id отсутствует")
        return False

    chat_id_str = str(chat_id).strip()
    api_url = f"https://api.telegram.org/bot{API_TOKEN}/sendDocument"

    try:
        # Если передано оригинальное имя файла, используем его, иначе берём имя файла из пути
        if original_filename is None:
            import os
            original_filename = os.path.basename(document_path)
        files = {'document': (original_filename, open(document_path, 'rb'))}
        data = {'chat_id': chat_id_str}
        if caption:
            data['caption'] = caption
            data['parse_mode'] = 'HTML'
        response = requests.post(api_url, files=files, data=data, timeout=30)
        if response.status_code == 200:
            logging.info(f"Документ успешно отправлен пользователю {chat_id_str}")
            return True
        else:
            error_data = response.json() if response.content else {"description": "Unknown error"}
            logging.error(f"Не удалось отправить документ: {error_data.get('description', 'Unknown error')}")
            return False
    except Exception as e:
        logging.error(f"Ошибка при отправке документа пользователю {chat_id}: {str(e)}")
        return False

# Функция для отправки уведомлений пользователю
async def send_notification(chat_id, message):
    try:
        # Проверка валидности chat_id
        if not chat_id:
            logging.error(f"Невозможно отправить сообщение: chat_id отсутствует")
            return False

        # Проверка на manual_ в chat_id (для вручную созданных пользователей)
        if isinstance(chat_id, str) and chat_id.startswith('manual_'):
            logging.warning(f"Попытка отправки сообщения вручную созданному пользователю: {chat_id}")
            return False

        # Преобразование chat_id в строку, если это число
        chat_id_str = str(chat_id).strip()

        # Детальное логирование для отладки
        logging.info(f"Отправка сообщения пользователю {chat_id_str}: {message[:50]}...")

        try:
            # Отправка сообщения через бота напрямую без timeout
            await bot.send_message(chat_id=chat_id_str, text=message)
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str}")
            return True
        except TelegramAPIError as api_error:
            # Обработка ошибок API Telegram
            logging.warning(f"Ошибка API Telegram: {str(api_error)}. Пробуем без HTML...")
            clean_message = re.sub(r'<[^>]*>', '', message)
            await bot.send_message(chat_id=chat_id_str, text=clean_message)
            logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
            return True
        except Exception as msg_error:
            # Если первая попытка не удалась, попробуем отправить без форматирования
            logging.warning(f"Ошибка при отправке сообщения: {str(msg_error)}. Пробуем без парсинга HTML...")

            # Удаляем все HTML-теги из сообщения
            clean_message = re.sub(r'<[^>]*>', '', message)
            try:
                await bot.send_message(chat_id=chat_id_str, text=clean_message)
                logging.info(f"Сообщение успешно отправлено пользователю {chat_id_str} (без HTML)")
                return True
            except Exception as e:
                logging.error(f"Не удалось отправить сообщение даже без HTML: {str(e)}")
                return False

    except Exception as e:
        # Подробный лог ошибки
        logging.error(f"Ошибка отправки уведомления пользователю {chat_id}: {str(e)}")

        # Дополнительная информация для отладки
        try:
            error_type = type(e).__name__
            logging.error(f"Тип ошибки: {error_type}")

            if hasattr(e, 'with_traceback'):
                import traceback
                error_trace = ''.join(traceback.format_tb(e.__traceback__))
                logging.error(f"Трассировка: {error_trace}")
        except:
            pass

        return False

# Function to create inline keyboard for tickets
async def create_tickets_keyboard(tickets, page=0, items_per_page=3):
    builder = InlineKeyboardBuilder()
    start_idx = page * items_per_page
    end_idx = start_idx + items_per_page
    current_page_tickets = tickets[start_idx:end_idx]

    for ticket in current_page_tickets:
        status_text = "Новая" if ticket.status == "new" else \
                    "В работе" if ticket.status == "in_progress" else \
                    "Решена" if ticket.status == "resolved" else \
                    "Неактуальна" if ticket.status == "irrelevant" else "Закрыта"
        created_date = ticket.created_at.strftime('%d.%m.%Y')
        title_display = ticket.title
        if len(title_display) > 25:
            title_display = title_display[:22] + "..."
        button_text = f"📅 {created_date} | {status_text}\n📝 {title_display}"
        builder.row(InlineKeyboardButton(
            text=button_text,
            callback_data=f"select_ticket:{ticket.id}"
        ))

    navigation_buttons = []
    page_count = (len(tickets) + items_per_page - 1) // items_per_page
    # Кнопка "Назад" (если не на первой странице)
    if page > 0:
        navigation_buttons.append(InlineKeyboardButton(
            text="◀️ Назад",
            callback_data=f"page:{page-1}"
        ))
    # Кнопка с номером страницы (неактивная)
    navigation_buttons.append(InlineKeyboardButton(
        text=f"📄 {page+1}/{page_count}",
        callback_data="page_info"
    ))
    # Кнопка "Вперед" (если не на последней странице)
    if (page + 1) * items_per_page < len(tickets):
        navigation_buttons.append(InlineKeyboardButton(
            text="Вперед ▶️",
            callback_data=f"page:{page+1}"
        ))
    builder.row(*navigation_buttons)
    return builder.as_markup()

# Function to update user's last activity timestamp
async def update_user_activity(user_id, state: FSMContext):
    """Update the user's last activity timestamp in their state data"""
    current_time = datetime.datetime.now().isoformat()
    await state.update_data(last_activity=current_time)
    logging.debug(f"Updated last activity for user {user_id} to {current_time}")

# Start command handler
@dp.message(Command("start"))
async def send_welcome(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        # Check if user exists
        user = get_user_by_chat_id(message.chat.id, user_db)

        if user:
            await message.answer(f"Привет, {user.full_name}! Вы уже зарегистрированы в системе.\n"
                               f"Я - бот для системы обработки заявок ОБУЗ КГКБСМП. Вот перечень команд, которые я могу обрабатывать:\n"
                               f"/start - Начать работу с ботом или зарегистрироваться\n"
                               f"/new_ticket - Создать новую заявку\n"
                               f"/tickets - Выбрать активную заявку или просмотреть сообщения по ней\n\n"
                               f"Внимание: если в чате не будет активности в течение 12 часов, активная заявка будет очищена, "
                               f"и вам потребуется выбрать её снова через команду /tickets.")
        else:
            # Send GDPR consent message
            gdpr_text = (
                "Добро пожаловать в систему поддержки ОБУЗ КГКБСМП!\n\n"
                "Перед регистрацией в системе, пожалуйста, ознакомьтесь с информацией о обработке персональных данных:\n\n"
                "1. Ваши персональные данные (ФИО, должность, отделение, номер кабинета) будут храниться в защищенной базе данных системы.\n"
                "2. Данные используются исключительно для идентификации пользователей и обработки заявок в системе.\n"
                "3. Мы не передаем ваши данные третьим лицам.\n"
                "4. Вы имеете право на удаление ваших данных из системы по запросу.\n\n"
                "Для продолжения регистрации, пожалуйста, подтвердите свое согласие на обработку персональных данных."
            )

            # Create inline keyboard for consent
            keyboard = InlineKeyboardBuilder()
            keyboard.add(InlineKeyboardButton(text="Согласен", callback_data="gdpr_agree"))
            keyboard.add(InlineKeyboardButton(text="Отказаться", callback_data="gdpr_decline"))

            await message.answer(gdpr_text, reply_markup=keyboard.as_markup())
            await state.set_state(RegistrationStates.waiting_for_gdpr_consent)
    finally:
        user_db.close()

# Handle GDPR consent callback
@dp.callback_query(F.data.startswith("gdpr_"))
async def process_gdpr_consent(callback: CallbackQuery, state: FSMContext):
    action = callback.data.split("_")[1]

    if action == "agree":
        # Сохраняем согласие на обработку ПД
        await state.update_data(privacy_consent=True, consent_date=datetime.datetime.utcnow())

        await callback.message.answer("Спасибо за согласие! Теперь продолжим процесс регистрации.\n"
                                     "Пожалуйста, введите ваше ФИО:")
        await state.set_state(RegistrationStates.waiting_for_fullname)
    else:
        await callback.message.answer("Вы отказались от обработки персональных данных.\n"
                                     "К сожалению, без этого согласия вы не можете использовать систему поддержки.\n"
                                     "Если вы измените решение, используйте команду /start для начала регистрации.")
        await state.clear()

    await callback.answer()

# Process fullname input
@dp.message(RegistrationStates.waiting_for_fullname)
async def process_fullname(message: types.Message, state: FSMContext):
    if not all(c.isalpha() or c.isspace() for c in message.text):
        await message.answer("ФИО должно содержать только буквы и пробелы. Пожалуйста, попробуйте снова:")
        return

    await state.update_data(full_name=message.text)
    await state.set_state(RegistrationStates.waiting_for_position)
    await message.answer("Спасибо! Теперь введите вашу должность:")
    await update_user_activity(message.chat.id, state)

@dp.message(RegistrationStates.waiting_for_position)
async def process_position(message: types.Message, state: FSMContext):
    await state.update_data(position=message.text)
    await state.set_state(RegistrationStates.waiting_for_department)
    await message.answer("Спасибо! Теперь введите ваше отделение:")
    await update_user_activity(message.chat.id, state)

# Process department input
@dp.message(RegistrationStates.waiting_for_department)
async def process_department(message: types.Message, state: FSMContext):
    await state.update_data(department=message.text)
    await state.set_state(RegistrationStates.waiting_for_office)
    await message.answer("Спасибо! Наконец, введите номер вашего кабинета:")
    await update_user_activity(message.chat.id, state)

# Process office input and continue registration (ask for phone)
@dp.message(RegistrationStates.waiting_for_office)
async def process_office(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        await state.update_data(office=message.text)
        await message.answer("Спасибо! Теперь введите ваш номер телефона (можно пропустить, отправив '-'):")
        await state.set_state(RegistrationStates.waiting_for_phone)
        await update_user_activity(message.chat.id, state)
    finally:
        user_db.close()

# Process phone input
@dp.message(RegistrationStates.waiting_for_phone)
async def process_phone(message: types.Message, state: FSMContext):
    phone = None
    if message.text != "-":
        # Проверка формата телефона (можно добавить регулярное выражение)
        phone = message.text

    await state.update_data(phone=phone)
    await message.answer("Спасибо! Последний шаг - введите ваш email (можно пропустить, отправив '-'):")
    await state.set_state(RegistrationStates.waiting_for_email)
    await update_user_activity(message.chat.id, state)  # Update user activity

# Process email input and complete registration
@dp.message(RegistrationStates.waiting_for_email)
async def process_email(message: types.Message, state: FSMContext):
    user_db = SessionLocal()
    try:
        email = None
        if message.text != "-":
            email = message.text

        await state.update_data(email=email)
        data = await state.get_data()

        # --- Проверка на существующего пользователя ---
        existing_user = user_db.query(User).filter(
            (User.chat_id == str(message.chat.id)) | (User.email == email)
        ).first()
        if existing_user:
            await message.answer(
                "Пользователь с таким Telegram уже зарегистрирован или email уже используется.\n"
                "Если вы считаете, что это ошибка — обратитесь к администратору."
            )
            await state.clear()
            return

        # --- Создание нового пользователя ---
        new_user = User(
            full_name=data['full_name'],
            position=data['position'],
            department=data['department'],
            office=data['office'],
            phone=data.get('phone'),
            email=data.get('email'),
            chat_id=str(message.chat.id),
            role="agent",
            privacy_consent=data.get('privacy_consent', False),
            consent_date=data.get('consent_date'),
            is_confirmed=False,
            is_active=True
        )

        user_db.add(new_user)
        user_db.commit()

        await message.answer(
            f"Регистрация успешно завершена, {new_user.full_name}!✅\n\n"
            f"⚠️ Ваш аккаунт находится на проверке у администратора. "
            f"До подтверждения профиля некоторые функции будут ограничены.\n\n"
            f"Вы сможете просматривать свой профиль по команде /profile, "
            f"но создание заявок станет доступно только после подтверждения.\n\n"
            f"Если вам срочно требуется доступ, обратитесь к администратору системы."
        )

        # Clear state and update activity
        await state.clear()
        await update_user_activity(message.chat.id, state)
    finally:
        user_db.close()

@dp.message(Command("new_ticket"))
async def new_ticket(message: types.Message, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Проверка статуса пользователя
        status, error_msg, user = await check_user_status(message.chat.id, user_db)
        if not status:
            await message.answer(error_msg)
            return

        # Получаем список активных категорий
        categories = ticket_db.query(TicketCategory).filter(TicketCategory.is_active == True).all()

        if not categories:
            await message.answer("К сожалению, в системе не настроены категории заявок. Обратитесь к администратору.")
            return

        # Создаем клавиатуру с категориями
        keyboard = InlineKeyboardBuilder()
        for category in categories:
            keyboard.add(InlineKeyboardButton(
                text=category.name,
                callback_data=f"category:{category.id}"
            ))
        keyboard.adjust(1)  # По одной кнопке в строке

        await message.answer("Создание новой заявки. Пожалуйста, выберите категорию заявки:",
                           reply_markup=keyboard.as_markup())
        await state.set_state(TicketStates.waiting_for_category)
        await update_user_activity(message.chat.id, state)  # Update user activity
    finally:
        user_db.close()
        ticket_db.close()

# Handle category selection callback
@dp.callback_query(F.data.startswith("category:"))
async def process_category_selection(callback: CallbackQuery, state: FSMContext):
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Extract category ID from callback data
        category_id = callback.data.split(":")[1]

        # Get the category name
        category = ticket_db.query(TicketCategory).filter(TicketCategory.id == category_id).first()
        if not category:
            await callback.message.answer("Ошибка: выбранная категория не найдена.")
            await callback.answer()
            return

        # Save category selection to state
        await state.update_data(category_id=category_id, category_name=category.name)

        # Ask for ticket title
        await callback.message.answer(f"Вы выбрали категорию: <b>{category.name}</b>.\n\nТеперь введите заголовок заявки:", parse_mode="HTML")
        await state.set_state(TicketStates.waiting_for_title)

        # Check user status
        status, _, user = await check_user_status(callback.message.chat.id, user_db)
        await callback.answer()
        await update_user_activity(callback.message.chat.id, state)
    finally:
        user_db.close()
        ticket_db.close()

# --- Ticket Title Handler ---
@dp.message(TicketStates.waiting_for_title)
async def process_ticket_title(message: types.Message, state: FSMContext):
    title = message.text.strip()
    if not title or len(title) < 3:
        await message.answer("Пожалуйста, введите корректный заголовок (минимум 3 символа):")
        return
    await state.update_data(title=title)
    await message.answer("Опишите подробно вашу проблему или вопрос:")
    await state.set_state(TicketStates.waiting_for_description)
    await update_user_activity(message.chat.id, state)

# --- Ticket Description Handler ---
@dp.message(TicketStates.waiting_for_description)
async def process_ticket_description(message: types.Message, state: FSMContext):
    description = message.text.strip()
    if not description or len(description) < 5:
        await message.answer("Пожалуйста, опишите проблему подробнее (минимум 5 символов):")
        return
    await state.update_data(description=description)
    # For simplicity, skip priority selection and go to attachments
    await message.answer(
        "Если хотите, прикрепите до 5 файлов (фото, документы, скриншоты, до 5 МБ каждый).\n"
        "Отправьте файлы по одному или несколько подряд.\n"
        "Когда закончите, нажмите кнопку <b>\"Готово\"</b> или напишите 'Готово'.",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="Готово", callback_data="attachments_done")]]
        )
    )
    await state.update_data(attachments=[])
    await state.set_state(TicketStates.collecting_attachments)
    await update_user_activity(message.chat.id, state)

# Handle photo attachment in Telegram
@dp.message(F.photo)
async def handle_photo(message: types.Message, state: FSMContext):
    # Check if we're in collecting attachments state
    current_state = await state.get_state()

    if current_state == TicketStates.collecting_attachments.state:
        # We're already collecting attachments, process this as an attachment
        await collect_attachments(message, state)
    else:
        # Normal photo message, tell user they can create a ticket with it
        await message.answer(
            "Отличное фото! Если вы хотите создать заявку с этим изображением, "
            "используйте команду /new_ticket, а затем прикрепите фото на этапе вложений."
        )

# Handle document attachment in Telegram
@dp.message(F.document)
async def handle_document(message: types.Message, state: FSMContext):
    # Check if we're in collecting attachments state
    current_state = await state.get_state()

    if current_state == TicketStates.collecting_attachments.state:
        # We're already collecting attachments, process this as an attachment
        await collect_attachments(message, state)
    else:
        # Normal document message, tell user they can create a ticket with it
        await message.answer(
            "Спасибо за документ! Если вы хотите создать заявку с этим файлом, "
            "используйте команду /new_ticket, а затем прикрепите файл на этапе вложений."
        )

# Function to download file from Telegram
async def download_telegram_file(file_id, destination_dir, custom_filename=None):
    try:
        file_info = await bot.get_file(file_id)
        file_path = file_info.file_path

        # Create directory if it doesn't exist
        if not os.path.exists(destination_dir):
            os.makedirs(destination_dir)

        # Define destination path
        if custom_filename:
            destination = os.path.join(destination_dir, custom_filename)
        else:
            # Extract original filename from path or generate one
            original_filename = os.path.basename(file_path)
            timestamp = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
            destination = os.path.join(destination_dir, f"{timestamp}_{original_filename}")

        # Download the file
        await bot.download_file(file_path, destination)
        return destination
    except Exception as e:
        logging.error(f"Error downloading file from Telegram: {e}")
        return None

# --- Collect Attachments Handler ---
MAX_ATTACHMENTS = 5
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5 MB

@dp.message(TicketStates.collecting_attachments, F.content_type.in_({"photo", "document", "video", "audio"}))
async def collect_attachments(message: types.Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])
    if len(attachments) >= MAX_ATTACHMENTS:
        await message.answer(f"Вы уже прикрепили максимальное количество файлов ({MAX_ATTACHMENTS}). Нажмите 'Готово' для продолжения.")
        return

    file_id = None
    file_type = None
    file_name = None
    file_size = None

    if message.content_type == "photo":
        # Get the largest photo
        photo = message.photo[-1]
        file_id = photo.file_id
        file_type = "photo"
        file_size = photo.file_size
        file_name = f"photo_{file_id}.jpg"
    elif message.content_type == "document":
        file_id = message.document.file_id
        file_type = "document"
        file_name = message.document.file_name or f"document_{file_id}"
        file_size = message.document.file_size
    elif message.content_type == "video":
        file_id = message.video.file_id
        file_type = "video"
        file_name = f"video_{file_id}.mp4"
        file_size = message.video.file_size
    elif message.content_type == "audio":
        file_id = message.audio.file_id
        file_type = "audio"
        file_name = message.audio.file_name or f"audio_{file_id}.mp3"
        file_size = message.audio.file_size

    if file_size is not None and file_size >= MAX_FILE_SIZE:
        await message.answer("Файл слишком большой (максимум 5 МБ). Пожалуйста, отправьте файл меньшего размера.")
        return

    # Download file to uploads directory
    try:
        file = await bot.get_file(file_id)
        file_path = file.file_path
        local_dir = "uploads"
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)
        local_path = os.path.join(local_dir, file_name)
        await bot.download_file(file_path, destination=local_path)
    except Exception as e:
        logging.error(f"Ошибка загрузки файла: {e}")
        await message.answer("Не удалось сохранить файл. Попробуйте еще раз или отправьте другой файл.")
        return

    # Save attachment info in state
    attachments.append({
        "file_id": file_id,
        "file_type": file_type,
        "file_name": file_name,
        "file_path": local_path
    })
    await state.update_data(attachments=attachments)

    await message.answer(f"Файл <b>{file_name}</b> успешно прикреплен ({len(attachments)}/{MAX_ATTACHMENTS}).", parse_mode="HTML")
    if len(attachments) >= MAX_ATTACHMENTS:
        await message.answer("Вы достигли лимита файлов. Нажмите 'Готово' для продолжения.")

@dp.message(TicketStates.collecting_attachments)
async def handle_text_in_attachments(message: types.Message, state: FSMContext):
    # User can type "Готово" or "готово" to finish
    if message.text and message.text.strip().lower() in {"готово", "done", "готов", "end", "finish"}:
        await finish_attachments(message, state)
    else:
        await message.answer("Пожалуйста, прикрепите файл или нажмите 'Готово', когда закончите.")

@dp.callback_query(F.data == "attachments_done")
async def finish_attachments_callback(callback: CallbackQuery, state: FSMContext):
    await finish_attachments(callback.message, state)
    await callback.answer()

async def finish_attachments(message: types.Message, state: FSMContext):
    data = await state.get_data()
    attachments = data.get("attachments", [])
    await message.answer("Спасибо! Ваша заявка будет сохранена и отправлена на рассмотрение.")
    # Save ticket to DB
    user_db = SessionLocal()
    ticket_db = SessionLocal()
    try:
        status, _, user = await check_user_status(message.chat.id, user_db)
        if not status or not user:
            await message.answer("Ошибка: не удалось определить пользователя.")
            return
        ticket = Ticket(
            title=data.get("title"),
            description=data.get("description"),
            category_id=data.get("category_id"),
            creator_chat_id=str(message.chat.id),
            status="new",
            priority="normal",  # При создании из ТГ всегда средний приоритет
            created_at=datetime.datetime.utcnow(),
            updated_at=datetime.datetime.utcnow()
        )
        ticket_db.add(ticket)
        ticket_db.commit()
        ticket_db.refresh(ticket)

        # Save attachments
        for att in attachments:
            attachment = Attachment(
                ticket_id=ticket.id,
                file_name=att["file_name"],
                file_path=att["file_path"],
                file_type=att["file_type"]
            )
            ticket_db.add(attachment)
        ticket_db.commit()

        await message.answer(f"Заявка <b>#{ticket.id}</b> успешно создана!\n\n"
                             f"Заголовок: <b>{ticket.title}</b>\n"
                             f"Категория: <b>{data.get('category_name')}</b>\n"
                             f"Статус: Новая\n"
                             f"Прикреплено файлов: {len(attachments)}",
                             parse_mode="HTML")
        await state.clear()
    finally:
        user_db.close()
        ticket_db.close()

# Команда для выбора заявки
@dp.message(Command("tickets")) # Changed from "ticket" to "tickets"
async def select_ticket(message: types.Message, state: FSMContext):
    logging.info(f"User {message.from_user.id} triggered /tickets command") # Added logging
    user_db = SessionLocal()
    ticket_db = SessionLocal()

    try:
        # Проверка статуса пользователя
        status, error_msg, user = await check_user_status(message.chat.id, user_db)
        if not status:
            await message.answer(error_msg)
            return

        # Получаем все заявки пользователя, отсортированные по дате создания (новые сверху)
        tickets = ticket_db.query(Ticket).filter(
            Ticket.creator_chat_id == str(message.chat.id)
        ).order_by(Ticket.created_at.desc()).all()

        if not tickets:
            await message.answer("У вас нет заявок. Используйте /new_ticket для создания новой заявки.")
            return

        # Сохраняем все заявки в состоянии пользователя для дальнейшей пагинации
        ticket_data = [{
            "id": t.id,
            "title": t.title,
            "status": t.status,
            "created_at": t.created_at.isoformat(),
            "resolved_at": t.updated_at.isoformat() if t.status in ["resolved", "irrelevant", "closed"] else None
        } for t in tickets]
        await state.update_data(tickets=ticket_data, current_page=0)

        # Создаем клавиатуру с пагинацией
        keyboard = await create_tickets_keyboard(tickets, page=0)

        # Формируем информативное сообщение
        total_tickets = len(tickets)
        active_tickets = sum(1 for t in tickets if t.status in ["new", "in_progress"])

        message_text = (
            f"<b>Ваши заявки ({total_tickets})</b>\n"
            f"Активных заявок: {active_tickets}\n\n"
            f"Выберите заявку из списка ниже:"
        )

        await message.answer(message_text, reply_markup=keyboard, parse_mode="HTML")
        await update_user_activity(message.chat.id, state)  # Update user activity

    finally:
        user_db.close()
        ticket_db.close()

# Callback handler for selecting a ticket from the inline keyboard
@dp.callback_query(F.data.startswith("select_ticket:"))
async def process_select_ticket(callback: CallbackQuery, state: FSMContext):
    ticket_db = SessionLocal()
    user_db = SessionLocal()
    try:
        ticket_id = int(callback.data.split(":")[1])
        status, error_msg, user = await check_user_status(callback.from_user.id, user_db)
        if not status:
            await callback.answer(error_msg, show_alert=True)
            return

        ticket = ticket_db.query(Ticket).filter(Ticket.id == ticket_id, Ticket.creator_chat_id == str(callback.from_user.id)).first()
        if not ticket:
            await callback.answer("Заявка не найдена или у вас нет к ней доступа.", show_alert=True)
            return

        await callback.message.answer(f"Вы выбрали заявку: <b>#{ticket.id} - {ticket.title}</b>.\nТеперь ваши сообщения будут направляться в этот чат.", parse_mode="HTML")
        await clear_user_chat(callback.from_user.id, bot)
        await display_last_10_messages(ticket_id, callback.from_user.id, bot, ticket_db, state)
        await state.update_data(active_ticket_id=ticket_id)
        await state.set_state(ActiveTicketStates.chatting)
        await callback.answer()
    finally:
        ticket_db.close()
        user_db.close()

# 1. Глобальный словарь для времени последнего уведомления
LAST_NOTIFICATION = {}  # {(chat_id, ticket_id): timestamp}

# 2. Исправить функцию очистки чата
async def clear_user_chat(user_id, bot):
    try:
        await bot.send_message(chat_id=user_id, text="---")
        await bot.send_message(chat_id=user_id, text="---")
    except Exception as e:
        import logging
        logging.error(f"Ошибка при очистке чата пользователя {user_id}: {e}")

# 3. Исправить функцию display_last_10_messages
async def display_last_10_messages(ticket_id, user_id, bot, ticket_db, state):
    # Перед историей отправляем сообщение о "очистке чата"
    await bot.send_message(chat_id=user_id, text="Чат очищен. История выбранной заявки:")
    for _ in range(3):
        await bot.send_message(chat_id=user_id, text="---")

    # Получаем до 30 сообщений для заявки, сортировка по возрастанию (старые сверху)
    messages = ticket_db.query(Message)\
        .filter(Message.ticket_id == ticket_id)\
        .order_by(Message.created_at)\
        .limit(30)\
        .all()

    if not messages:
        await bot.send_message(
            chat_id=user_id,
            text="В этой заявке пока нет сообщений."
        )
    else:
        from models.ticket_models import Attachment
        msg_ids = [msg.id for msg in messages]
        attachments = ticket_db.query(Attachment).filter(Attachment.message_id.in_(msg_ids)).all()
        att_map = {}
        for att in attachments:
            att_map.setdefault(att.message_id, []).append(att)

        for msg in messages:
            timestamp = msg.created_at.strftime('%d.%m.%Y %H:%M')
            sender_name = msg.sender_name
            text = f"<b>{sender_name}</b> ({timestamp}):\n{msg.content}" if msg.content else f"<b>{sender_name}</b> ({timestamp})"
            msg_attachments = att_map.get(msg.id, [])
            if msg_attachments:
                for att in msg_attachments:
                    file_path = os.path.join('uploads', att.file_path) if not att.file_path.startswith('uploads') else att.file_path
                    if not os.path.exists(file_path):
                        await bot.send_message(chat_id=user_id, text=f"Файл не найден: {att.file_name}")
                        continue
                    try:
                        if att.is_image:
                            await bot.send_photo(chat_id=user_id, photo=FSInputFile(file_path, filename=att.file_name), caption=text, parse_mode='HTML')
                        else:
                            await bot.send_document(chat_id=user_id, document=FSInputFile(file_path, filename=att.file_name), caption=text, parse_mode='HTML')
                    except Exception as e:
                        import logging
                        logging.error(f"Ошибка отправки файла {file_path}: {e}")
                        await bot.send_message(chat_id=user_id, text=f"[Ошибка отправки файла] {att.file_name}")
                    text = None
            else:
                await bot.send_message(
                    chat_id=user_id,
                    text=text,
                    parse_mode='HTML'
                )
    # После сообщений пересылаем все файлы-заявки без message_id
    ticket_attachments = ticket_db.query(Attachment).filter(
        Attachment.ticket_id == ticket_id,
        Attachment.message_id == None
    ).all()
    for att in ticket_attachments:
        file_path = os.path.join('uploads', att.file_path) if not att.file_path.startswith('uploads') else att.file_path
        if not os.path.exists(file_path):
            await bot.send_message(chat_id=user_id, text=f"Файл не найден: {att.file_name}")
            continue
        try:
            if att.is_image:
                await bot.send_photo(chat_id=user_id, photo=FSInputFile(file_path, filename=att.file_name), caption="Вложение к заявке", parse_mode='HTML')
            else:
                await bot.send_document(chat_id=user_id, document=FSInputFile(file_path, filename=att.file_name), caption="Вложение к заявке", parse_mode='HTML')
        except Exception as e:
            import logging
            logging.error(f"Ошибка отправки файла {file_path}: {e}")
            await bot.send_message(chat_id=user_id, text=f"[Ошибка отправки файла] {att.file_name}")

# 4. Исправить handle_new_message_from_site для уведомлений с инлайн-кнопкой и лимитом 1 час
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
import time

async def handle_new_message_from_site(ticket_id: int, sender_name: str, message_text: str, chat_id: str, timestamp_str: Optional[str] = None):
    ticket_db = SessionLocal()
    state_data = None
    try:
        try:
            message_timestamp = datetime.datetime.fromisoformat(timestamp_str) if timestamp_str else datetime.datetime.utcnow()
        except (ValueError, TypeError):
            logging.warning(f"Invalid timestamp format received: {timestamp_str}. Using current UTC time.")
            message_timestamp = datetime.datetime.utcnow()

        # Deduplication check
        if is_duplicate_message(chat_id, message_text, message_timestamp):
            logging.info(f"Duplicate message detected from site for ticket {ticket_id}, chat {chat_id}. Skipping.")
            return

        # Save message to DB (assuming it's not a duplicate)
        new_msg = Message(
            ticket_id=ticket_id,
            sender_name=sender_name, # Name of the sender from the website
            content=message_text,
            created_at=message_timestamp, # Use parsed or current time
            is_internal=True # Message from website/operator
        )
        ticket_db.add(new_msg)
        ticket_db.commit()
        ticket_db.refresh(new_msg)

        # Получаем заявку
        ticket = ticket_db.query(Ticket).filter(Ticket.id == ticket_id).first()
        ticket_title = ticket.title if ticket else f"#{ticket_id}"

        # Проверяем активную заявку пользователя
        from aiogram.fsm.storage.base import StorageKey
        user_fsm_context = FSMContext(storage=dp.storage, key=StorageKey(bot_id=bot.id, user_id=int(chat_id), chat_id=int(chat_id)))
        state_data = await user_fsm_context.get_data()
        active_ticket_id_in_state = state_data.get("active_ticket_id")

        now = time.time()
        notif_key = (chat_id, ticket_id)
        if active_ticket_id_in_state != ticket_id:
            # Проверяем лимит уведомлений (1 час)
            if now - LAST_NOTIFICATION.get(notif_key, 0) > 3600:
                keyboard = InlineKeyboardMarkup(
                    inline_keyboard=[
                        [InlineKeyboardButton(
                            text=f"Открыть заявку: {ticket_title}",
                            callback_data=f"select_ticket:{ticket_id}"
                        )]
                    ]
                )
                await bot.send_message(
                    chat_id,
                    f"🔔 В заявке <b>{ticket_title}</b> новое сообщение.",
                    parse_mode="HTML",
                    reply_markup=keyboard
                )
                LAST_NOTIFICATION[notif_key] = now
            return
        # Если активная заявка совпадает — пересылать как обычно
        await display_last_10_messages(ticket_id, int(chat_id), bot, ticket_db, user_fsm_context)

    except Exception as e:
        logging.error(f"Ошибка при обработке сообщения с сайта для заявки {ticket_id}: {e}")
    finally:
        ticket_db.close()

# 5. В check_inactive_users: если не было активности 6 часов, сбрасывать active_ticket_id и очищать чат
async def check_inactive_users():
    try:
        while True:
            logging.info("Checking for inactive users...")
            try:
                if not hasattr(dp, 'storage') or not dp.storage:
                    logging.warning("Storage is not properly initialized. Skipping inactive user check.")
                    await asyncio.sleep(3600)
                    continue
                if hasattr(dp.storage, 'data') and dp.storage.data:
                    states_data = dp.storage.data
                    current_time = datetime.datetime.now()
                    for user_id, user_data in states_data.items():
                        if isinstance(user_data, dict) and 'data' in user_data:
                            state_data = user_data['data']
                            active_ticket_id = state_data.get('active_ticket_id')
                            last_activity = state_data.get('last_activity')
                            if active_ticket_id and last_activity:
                                try:
                                    last_activity_time = datetime.datetime.fromisoformat(last_activity)
                                    inactive_hours = (current_time - last_activity_time).total_seconds() / 3600
                                    if inactive_hours >= 6:
                                        logging.info(f"User {user_id} has been inactive for {inactive_hours:.2f} hours. Clearing active ticket.")
                                        state_data['active_ticket_id'] = None
                                        try:
                                            await clear_user_chat(user_id, bot)
                                            await bot.send_message(
                                                chat_id=user_id,
                                                text="Активная заявка сброшена из-за отсутствия активности. Выберите заявку снова через /tickets."
                                            )
                                        except Exception as e:
                                            logging.error(f"Failed to notify user {user_id} about chat clearing: {str(e)}")
                                except (ValueError, TypeError) as e:
                                    logging.error(f"Error parsing last_activity for user {user_id}: {str(e)}")
                else:
                    logging.warning("Storage doesn't have 'data' attribute or it's empty. Unable to check inactive users.")
            except Exception as e:
                logging.error(f"Error accessing storage data: {str(e)}")
            await asyncio.sleep(3600)
    except Exception as e:
        logging.error(f"Error in inactive users check task: {str(e)}")
        if hasattr(e, '__traceback__'):
            import traceback
            error_trace = ''.join(traceback.format_tb(e.__traceback__))
            logging.error(f"Traceback: {error_trace}")

@dp.message(Command("my_tickets"))
async def show_my_tickets(message: types.Message, state: FSMContext):
    logging.info(f"User {message.from_user.id} triggered /my_tickets command") # Added logging
    # This command is being deprecated in favor of /ticket which provides more functionality.
    # We can either remove it or have it call the /ticket handler.
    # For now, let's inform the user and suggest /ticket.
    await message.answer("Команда /my_tickets более не используется. Пожалуйста, используйте команду /ticket для просмотра и выбора ваших заявок.")
    # Optionally, you could directly call the select_ticket handler:
    # await select_ticket(message, state)

@dp.message(Command("help"))
async def show_help(message: types.Message, state: FSMContext):
    logging.info(f"User {message.from_user.id} triggered /help command") # Added logging
    await message.answer("Я - бот для системы обработки заявок ОБУЗ КГКБСМП. Вот список доступных команд:\n"
                      "/start - Начать работу с ботом или зарегистрироваться\n"
                      "/new_ticket - Создать новую заявку\n"
                      "/tickets - Выбрать активную заявку и просмотреть сообщения по ней\n"
                      "/profile - Показать информацию о моем профиле\n"
                      "/pdn_policy - Политика обработки персональных данных\n"
                      "/help - Показать эту справку\n\n"
                      "Внимание: если в чате не будет активности в течение 12 часов, "
                      "активная заявка будет очищена, и вам потребуется выбрать её снова через команду /tickets.")
    await update_user_activity(message.chat.id, state)  # Update user activity

# Команда для отображения политики обработки персональных данных
@dp.message(Command("pdn_policy"))
async def show_pdn_policy(message: types.Message, state: FSMContext):
    try:
        # Путь к файлу с текстом политики
        policy_file_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "pdn_policy.txt")

        # Проверяем существование файла
        if os.path.exists(policy_file_path):
            # Читаем текст из файла
            with open(policy_file_path, "r", encoding="utf-8") as f:
                policy_text = f.read()

            # Форматируем текст для Telegram (добавляем HTML-форматирование)
            lines = policy_text.split('\n')
            if lines:
                formatted_text = f"<b>{lines[0]}</b>\n\n" + "\n".join(lines[1:])
            else:
                formatted_text = policy_text
            await message.answer(formatted_text, parse_mode="HTML")
        else:
            # Если файл не найден, используем встроенный текст
            gdpr_text = (
                "<b>Политика обработки персональных данных</b>\n\n"
                "В соответствии с требованиями Федерального закона от 27.07.2006 г. № 152-ФЗ «О персональных данных»:\n\n"
                "1. Ваши персональные данные (ФИО, должность, отделение, номер кабинета, телефон, email) "
                "хранятся в защищенной базе данных системы поддержки ОБУЗ КГКБСМП.\n\n"
                "2. Данные используются исключительно для идентификации пользователей и обработки заявок в системе поддержки.\n\n"
                "3. Мы не передаем ваши данные третьим лицам без вашего согласия, за исключением случаев, "
                "предусмотренных законодательством РФ.\n\n"
                "4. Вы имеете право на доступ к своим персональным данным, их обновление, удаление или ограничение обработки "
                "по запросу к администратору системы.\n\n"
                "5. Система хранит дату и время вашего согласия с политикой обработки персональных данных.\n\n"
                "6. Политика может быть изменена в соответствии с требованиями законодательства. "
                "В случае существенных изменений, вам будет предложено ознакомиться с обновленной версией.\n\n"
                "7. По всем вопросам относительно обработки ваших персональных данных вы можете обратиться "
                "к администратору системы поддержки.\n\n"
                "Используя бота поддержки ОБУЗ КГКБСМП, вы подтверждаете своё согласие с данной политикой."
            )
            await message.answer(gdpr_text, parse_mode="HTML")

            # Логируем ошибку
            logging.warning(f"Файл политики обработки ПДн не найден: {policy_file_path}")

    except Exception as e:
        logging.error(f"Ошибка при чтении файла политики обработки ПДн: {str(e)}")
        await message.answer("Произошла ошибка при получении текста политики обработки ПДн. Попробуйте позднее.")

    await update_user_activity(message.chat.id, state)  # Update user activity

# Profile command handler - показывает информацию о пользователе
@dp.message(Command("profile"))
async def show_profile(message: types.Message, state: FSMContext):
    user_db = SessionLocal()

    try:
        # Проверяем, зарегистрирован ли пользователь (без проверки статуса)
        user = get_user_by_chat_id(message.chat.id, user_db)

        if not user:
            await message.answer("Вы не зарегистрированы в системе. Используйте /start для регистрации.")
            return

        # Форматируем дату согласия
        consent_date_str = "Не указана"
        if user.consent_date:
            consent_date_str = user.consent_date.strftime('%d.%m.%Y %H:%M')

        # Форматируем дату создания профиля
        created_date_str = user.created_at.strftime('%d.%m.%Y %H:%M')

        # Получаем статусы активности и подтверждения
        confirmation_status = "✅ Подтвержден" if user.is_confirmed else "❌ Ожидает подтверждения"
        active_status = "✅ Активен" if user.is_active else "❌ Заблокирован"

        # Форматируем телефон и email, если они есть
        phone_str = user.phone if user.phone else "Не указан"
        email_str = user.email if user.email else "Не указан"

        # Формируем сообщение с информацией о профиле
        profile_text = (
            f"📋 <b>Ваш профиль</b>\n\n"
            f"👤 <b>ФИО:</b> {user.full_name}\n"
            f"🏢 <b>Должность:</b> {user.position}\n"
            f"🏥 <b>Отделение:</b> {user.department}\n"
            f"🚪 <b>Кабинет:</b> {user.office}\n"
            f"📱 <b>Телефон:</b> {phone_str}\n"
            f"📧 <b>Email:</b> {email_str}\n\n"
            f"🔐 <b>Статус профиля:</b> {active_status}, {confirmation_status}\n"
            f"📅 <b>Дата регистрации:</b> {created_date_str}\n"
            f"✍️ <b>Согласие на обработку ПДн:</b> {'Получено' if user.privacy_consent else 'Не получено'}\n"
            f"📆 <b>Дата согласия:</b> {consent_date_str}\n"
            f"👑 <b>Роль:</b> {'Администратор' if user.role == 'admin' else 'Куратор' if user.role == 'curator' else 'Пользователь'}\n"
        )

        # Добавляем сообщение с рекомендациями, если аккаунт не подтвержден или заблокирован
        if not user.is_confirmed:
            profile_text += (
                f"\n⚠️ <b>Внимание:</b> Ваш аккаунт ожидает подтверждения администратором. "
                f"До подтверждения вы не сможете создавать заявки и писать сообщения."
            )
        elif not user.is_active:
            profile_text += (
                f"\n⛔ <b>Внимание:</b> Ваш аккаунт заблокирован администратором. "
                f"Для выяснения причин обратитесь к администратору системы."
            )

        await message.answer(profile_text, parse_mode="HTML")
        await update_user_activity(message.chat.id, state)  # Update user activity

    finally:
        user_db.close()

# Function to handle new messages from the website (placeholder)
# This is where you would add deduplication logic
# For example, by checking message content + timestamp + sender against recent messages
RECENT_MESSAGES_CACHE = {} # Simple cache: {chat_id: [(message_hash, timestamp), ...]}
MAX_CACHE_SIZE_PER_CHAT = 10 # Store last 10 message hashes for deduplication
DUPLICATE_THRESHOLD_SECONDS = 5 # Time window (seconds) to consider a message a duplicate

def is_duplicate_message(chat_id: str, message_text: str, timestamp: datetime.datetime) -> bool:
    """Проверяет, является ли сообщение дубликатом."""
    message_hash = hash(message_text) # Simple hash, consider more robust hashing

    if chat_id not in RECENT_MESSAGES_CACHE:
        RECENT_MESSAGES_CACHE[chat_id] = []

    chat_cache = RECENT_MESSAGES_CACHE[chat_id]

    # Check against recent messages
    for h, ts in reversed(chat_cache): # Check newest first
        if h == message_hash and (timestamp - ts).total_seconds() < DUPLICATE_THRESHOLD_SECONDS:
            return True # Likely duplicate

    # Add current message to cache
    chat_cache.append((message_hash, timestamp))
    if len(chat_cache) > MAX_CACHE_SIZE_PER_CHAT:
        RECENT_MESSAGES_CACHE[chat_id] = chat_cache[-MAX_CACHE_SIZE_PER_CHAT:] # Keep cache size limited

    return False

# Function to start bot
async def start_bot():
    # Create uploads directory if it doesn't exist
    if not os.path.exists('uploads'):
        os.makedirs('uploads')

    # Start the background task for checking inactive users
    asyncio.create_task(check_inactive_users())

    # Start polling
    await dp.start_polling(bot)

# Main function to run the bot
def run_bot():
    """Start the Telegram bot"""
    if not _DEPENDENCIES_LOADED:
        logging.error("Телеграм бот не может быть запущен из-за отсутствия необходимых зависимостей.")
        logging.error("Пожалуйста, установите необходимые зависимости: pip install aiogram sqlalchemy nest_asyncio python-dotenv requests")
        return

    try:
        asyncio.run(start_bot())
    except Exception as e:
        logging.error(f"Error starting bot: {str(e)}")

@dp.callback_query(F.data.startswith("page:"))
async def process_ticket_pagination(callback: CallbackQuery, state: FSMContext):
    page = int(callback.data.split(":")[1])
    data = await state.get_data()
    tickets_data = data.get("tickets", [])
    # Восстанавливаем объекты Ticket из словарей (или получаем из БД при необходимости)
    # Здесь tickets_data — это список словарей, нужно получить объекты Ticket для передачи в create_tickets_keyboard
    ticket_db = SessionLocal()
    try:
        ticket_ids = [t["id"] for t in tickets_data]
        tickets = ticket_db.query(Ticket).filter(Ticket.id.in_(ticket_ids)).order_by(Ticket.created_at.desc()).all()
        # Сортируем в том же порядке, что и в tickets_data
        tickets = sorted(tickets, key=lambda t: ticket_ids.index(t.id))
        keyboard = await create_tickets_keyboard(tickets, page=page)
        await callback.message.edit_reply_markup(reply_markup=keyboard)
        await state.update_data(current_page=page)
        await callback.answer()
    finally:
        ticket_db.close()