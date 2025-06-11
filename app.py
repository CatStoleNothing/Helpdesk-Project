from flask import Flask, render_template, request, redirect, url_for, flash, abort, send_from_directory, jsonify, session
from dotenv import load_dotenv
import os
import functools
import jinja2
import asyncio
import threading
import logging
import nest_asyncio
from sqlalchemy.orm import joinedload
import hashlib
import json
import datetime
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import timedelta
from pytz import timezone, utc

from models.db_init import init_db, SessionLocal
from models.user_models import User
from models.ticket_models import (
    Ticket, Attachment, Message, DashboardMessage,
    DashboardAttachment, TicketCategory, AuditLog
)
from models.department_models import Department
from models.position_models import Position
from models.office_models import Office
from sqlalchemy import func, desc
from werkzeug.utils import secure_filename
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
import uuid

# Import bot notification function
from bot.bot import sync_send_notification

# Load environment variables
load_dotenv()

def admin_required(f):
    @functools.wraps(f)
    def decorated_function(*args, **kwargs):
        if not current_user.is_authenticated or current_user.role != 'admin':
            flash('У вас нет прав для доступа к этой странице', 'danger')
            return redirect(url_for('index'))
        return f(*args, **kwargs)
    return decorated_function

# Initialize Flask app
app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "your-secret-key-here")

# Добавляем фильтр datetime
@app.template_filter('datetime')
def format_datetime(value):
    if value is None:
        return ""
    return value.strftime('%d.%m.%Y %H:%M')

# Используем абсолютный путь для папки загрузок, чтобы она сохранялась между перезапусками
base_dir = os.path.abspath(os.path.dirname(__file__))
app.config['UPLOAD_FOLDER'] = os.path.join(base_dir, 'uploads')
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024  # 5 MB max upload

# Ensure uploads folder exists
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)

# Setup Flask-Login
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'

@login_manager.user_loader
def load_user(user_id):
    db = SessionLocal()
    user = db.get(User, int(user_id))
    db.close()
    return user

# Apply asyncio compatibility
nest_asyncio.apply()

# Initialize database
init_db()

# Проверяем наличие необходимых таблиц и при необходимости запускаем миграцию
def check_required_tables():
    ticket_db = SessionLocal()
    try:
        from sqlalchemy import inspect
        inspector = inspect(ticket_db.bind)
        tables = inspector.get_table_names()

        required_tables = [
            'tickets', 'messages', 'attachments', 'audit_logs', 'ticket_categories',
            'dashboard_messages', 'dashboard_attachments'
        ]

        missing_tables = [table for table in required_tables if table not in tables]

        if missing_tables:
            logging.warning(f"ВНИМАНИЕ: Следующие таблицы отсутствуют в базе данных: {', '.join(missing_tables)}")
            logging.warning("Автоматически запускаем миграцию базы данных...")

            # Закрываем текущее соединение перед выполнением миграции
            ticket_db.close()

        return True
    except Exception as e:
        logging.error(f"Ошибка при проверке таблиц: {str(e)}")
        return False
    finally:
        ticket_db.close()

check_result = check_required_tables()
if not check_result:
    logging.error("Не удалось выполнить автоматическую миграцию. Приложение может работать некорректно.")

# Вспомогательная функция для безопасного выполнения асинхронного кода из потоков
def run_async_in_thread(coro, *args, **kwargs):
    async def wrapper():
        try:
            return await coro(*args, **kwargs)
        except Exception as e:
            logging.error(f"Ошибка при выполнении асинхронного кода в потоке: {str(e)}")
            return False

    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        return loop.run_until_complete(wrapper())
    except Exception as e:
        logging.error(f"Не удалось выполнить асинхронный код в потоке: {str(e)}")
        return False
    finally:
        loop.close()

def log_user_action(user_id, action_type, description):
    """
    Логирует действие пользователя в системе.
    
    Args:
        user_id: ID пользователя, выполнившего действие
        action_type: Тип действия
        description: Описание действия
    """
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            logging.error(f"Не удалось найти пользователя с ID {user_id}")
            return False
            
        audit_log = AuditLog(
            actor_id=str(user_id),
            actor_name=user.full_name,
            action_type=action_type,
            description=description,
            entity_type='user',
            entity_id=str(user_id),
            is_pdn_related=True,
            timestamp=datetime.datetime.utcnow()
        )
        
        db.add(audit_log)
        db.commit()
        return True
    except Exception as e:
        logging.error(f"Ошибка при логировании действия пользователя: {str(e)}")
        db.rollback()
        return False
    finally:
        db.close()

# Добавляем фильтр nl2br для Jinja
@app.template_filter('nl2br')
def nl2br(value):
    if value:
        return jinja2.utils.markupsafe.Markup(value.replace('\n', '<br>'))
    return ""

# 404 Error handler
@app.errorhandler(404)
def page_not_found(e):
    if request.path == '/favicon.ico':
        return '', 204  # Нет содержимого
    return redirect(url_for('index'))

# Универсальный декоратор с поддержкой ролей (всегда использует current_user/Flask-Login)
def login_required_role(role=None):
    def wrapper(fn):
        @functools.wraps(fn)
        def decorated_view(*args, **kwargs):
            if not current_user.is_authenticated:
                flash('Пожалуйста, войдите в систему', 'error')
                return redirect(url_for('login', next=request.url))
            if role and getattr(current_user, 'role', None) not in role:
                flash('У вас нет доступа', 'error')
                return redirect(url_for('dashboard'))
            return fn(*args, **kwargs)
        return decorated_view
    return wrapper

# Добавляем функцию уведомления для обновления заявки
def notify_ticket_update(ticket, message, db, notification_type="update"):
    """
    Отправляет уведомление пользователю о изменении статуса заявки или новом сообщении.

    Args:
        ticket: Объект заявки
        message: Текст сообщения для отправки
        db: Сессия БД
        notification_type: Тип уведомления (update, message, etc.)
    """
    # Проверяем наличие chat_id
    if not ticket.creator_chat_id:
        logging.warning(f"Невозможно отправить уведомление: creator_chat_id отсутствует для заявки #{ticket.id}")
        return False

    try:
        # Отправляем уведомление
        result = sync_send_notification(ticket.creator_chat_id, message)

        # Логируем результат
        if result:
            logging.info(f"Уведомление успешно отправлено пользователю {ticket.creator_chat_id}")
            return True
        else:
            logging.warning(f"Не удалось отправить уведомление пользователю {ticket.creator_chat_id}")
            return False
    except Exception as e:
        logging.error(f"Ошибка при отправке уведомления пользователю {ticket.creator_chat_id}: {str(e)}")
        return False

# Вместо load_json_list('statuses.json') используем справочник статусов:
STATUSES = [
    {"id": "new", "name": "Новая"},
    {"id": "in_progress", "name": "В работе"},
    {"id": "resolved", "name": "Решена"},
    {"id": "irrelevant", "name": "Неактуально"},
    {"id": "closed", "name": "Закрыта"},
]

@app.route('/create_ticket', methods=['GET', 'POST'])
@login_required_role()
def create_ticket():
    ticket_db = SessionLocal()
    import sqlalchemy
    is_staff = getattr(current_user, 'role', None) in ["admin", "curator"]
    users = None
    if is_staff:
        user_db = SessionLocal()
        users = user_db.query(User).options(
            sqlalchemy.orm.joinedload(User.position),
            sqlalchemy.orm.joinedload(User.department)
        ).filter(User.is_active == True, User.is_confirmed == True).all()
        user_db.close()

    # Категории теперь только из БД
    categories = ticket_db.query(TicketCategory).filter(TicketCategory.is_active == True).all()

    if request.method == 'POST':
        title = request.form.get('title', '').strip()
        description = request.form.get('description', '').strip()
        category_id = request.form.get('category_id')
        # добавляем приоритет, если есть
        priority = request.form.get('priority', 'normal')
        status = request.form.get('status', 'open')
        # Новое: выбор или автоматический текущий creator
        if is_staff and request.form.get('creator_id'):
            creator_chat_id = request.form.get('creator_id')
        else:
            creator_chat_id = current_user.chat_id
        new_ticket = Ticket(
            title=title,
            description=description,
            category_id=category_id,
            priority=priority,
            status=status,
            creator_chat_id=creator_chat_id,
            created_at=datetime.datetime.utcnow()
        )
        ticket_db.add(new_ticket)
        ticket_db.commit()
        ticket_db.close()
        flash('Заявка успешно создана', 'success')
        return redirect(url_for('tickets'))
    ticket_db.close()
    return render_template(
        'create_ticket.html',
        categories=categories,
        users=users
    )

@app.route('/registration_approval', methods=['GET', 'POST'])
@login_required
def registration_approval():
    if not current_user.is_curator:
        flash('У вас нет прав для доступа к этой странице', 'danger')
        return redirect(url_for('index'))
    
    db = SessionLocal()
    try:
        if request.method == 'POST':
            user_id = request.form.get('user_id')
            action = request.form.get('action')
            
            if not user_id or not action:
                flash('Неверные параметры запроса', 'danger')
                return redirect(url_for('registration_approval'))
            
            user = db.get(User, user_id)
            if not user:
                flash('Пользователь не найден', 'danger')
                return redirect(url_for('registration_approval'))
            
            if action == 'approve':
                user.is_confirmed = True
                user.approved_by_id = current_user.id
                user.approved_at = datetime.utcnow()
                
                # Логируем действие
                log_user_action(
                    user_id=current_user.id,
                    action_type='approve_registration',
                    description=f'Подтверждена регистрация пользователя {user.full_name}'
                )
                
                flash('Регистрация успешно подтверждена', 'success')
                
            elif action == 'reject':
                rejection_reason = request.form.get('rejection_reason')
                if not rejection_reason:
                    flash('Необходимо указать причину отклонения', 'danger')
                    return redirect(url_for('registration_approval'))
                
                user.is_confirmed = False
                user.rejected_by_id = current_user.id
                user.rejected_at = datetime.utcnow()
                user.rejection_reason = rejection_reason
                
                # Логируем действие
                log_user_action(
                    user_id=current_user.id,
                    action_type='reject_registration',
                    description=f'Отклонена регистрация пользователя {user.full_name}. Причина: {rejection_reason}'
                )
                
                flash('Регистрация отклонена', 'success')
            
            db.commit()
            return redirect(url_for('registration_approval'))
        
        # Получаем списки пользователей
        pending_users = db.query(User).filter_by(is_confirmed=None).all()
        approved_users = db.query(User).filter_by(is_confirmed=True).all()
        rejected_users = db.query(User).filter_by(is_confirmed=False).all()
        
        return render_template('registration_approval.html',
                             pending_users=pending_users,
                             approved_users=approved_users,
                             rejected_users=rejected_users)
    finally:
        db.close()

@app.route('/edit_user/<int:user_id>', methods=['GET', 'POST'])
@login_required_role(['admin', 'curator'])
def edit_user(user_id):
    db = SessionLocal()
    try:
        user = db.get(User, user_id)
        if not user:
            db.close()
            abort(404)
        
        if request.method == 'POST':
            # Сохраняем старые значения для логирования изменений
            old_values = {
                'full_name': user.full_name,
                'position_id': user.position_id,
                'office_id': user.office_id,
                'phone': user.phone,
                'email': user.email,
                'is_active': user.is_active,
                'is_archived': user.is_archived,
                'archived_at': user.archived_at
            }
            
            # Обновляем данные пользователя
            user.full_name = request.form.get('full_name')
            user.position_id = request.form.get('position_id', type=int)
            user.office_id = request.form.get('office_id', type=int)
            user.phone = request.form.get('phone')
            user.email = request.form.get('email')
            # Получаем значения чекбоксов и даты
            is_archived = bool(request.form.get('is_archived'))
            archived_at_str = request.form.get('archived_at')
            archived_at = None
            if archived_at_str:
                try:
                    archived_at = datetime.datetime.strptime(archived_at_str, '%Y-%m-%d').date()
                except Exception:
                    archived_at = None
            
            # Логика увольнения и активности
            if is_archived:
                if not archived_at:
                    flash('Пожалуйста, укажите дату увольнения!', 'danger')
                    return redirect(url_for('edit_user', user_id=user_id))
                if archived_at <= datetime.date.today():
                    user.is_archived = True
                    user.is_active = False
                    user.archived_at = archived_at
                else:
                    user.is_archived = False
                    user.is_active = True
                    user.archived_at = archived_at
            else:
                user.is_archived = False
                user.archived_at = None
                user.is_active = bool(request.form.get('is_active'))
            
            # Остальные поля
            # user.is_active уже обработан выше
            
            # Формируем описание изменений для лога
            changes = []
            if old_values['full_name'] != user.full_name:
                changes.append(f"ФИО: {old_values['full_name']} → {user.full_name}")
            if old_values['position_id'] != user.position_id:
                old_position = db.get(Position, old_values['position_id'])
                new_position = db.get(Position, user.position_id)
                changes.append(f"Должность: {old_position.name if old_position else 'Не указана'} → {new_position.name if new_position else 'Не указана'}")
            if old_values['office_id'] != user.office_id:
                old_office = db.get(Office, old_values['office_id'])
                new_office = db.get(Office, user.office_id)
                changes.append(f"Кабинет: {old_office.name if old_office else 'Не указан'} → {new_office.name if new_office else 'Не указан'}")
            if old_values['phone'] != user.phone:
                changes.append(f"Телефон: {old_values['phone'] or 'Не указан'} → {user.phone or 'Не указан'}")
            if old_values['email'] != user.email:
                changes.append(f"Email: {old_values['email'] or 'Не указан'} → {user.email or 'Не указан'}")
            if old_values['is_active'] != user.is_active:
                changes.append(f"Статус: {'Активен' if old_values['is_active'] else 'Неактивен'} → {'Активен' if user.is_active else 'Неактивен'}")
            if old_values['is_archived'] != user.is_archived:
                changes.append(f"Уволен: {'Да' if old_values['is_archived'] else 'Нет'} → {'Да' if user.is_archived else 'Нет'}")
            if old_values['archived_at'] != user.archived_at:
                changes.append(f"Дата увольнения: {old_values['archived_at'] or 'Не указана'} → {user.archived_at or 'Не указана'}")
            
            try:
                db.commit()
                
                # Логируем изменения, если они были
                if changes:
                    log_user_action(
                        user_id=current_user.id,
                        action_type='edit_user',
                        description=f"Изменены данные пользователя {user.full_name}: {', '.join(changes)}"
                    )
                
                flash('Данные пользователя успешно обновлены', 'success')
                return redirect(url_for('users'))
            except Exception as e:
                db.rollback()
                flash(f'Ошибка при обновлении данных: {str(e)}', 'danger')
                return redirect(url_for('edit_user', user_id=user_id))
        
        positions = db.query(Position).all()
        offices = db.query(Office).all()
        return render_template('edit_user.html',
                             user=user,
                             positions=positions,
                             offices=offices)
    finally:
        db.close()

@app.route('/edit_category/<int:category_id>', methods=['GET', 'POST'])
@login_required_role(['curator'])
def edit_category(category_id):
    db = SessionLocal()
    category = db.query(TicketCategory).get(category_id)
    if not category:
        db.close()
        abort(404)
    if request.method == 'POST':
        category.name        = request.form.get('name', category.name).strip()
        category.description = request.form.get('description', category.description).strip()
        category.is_active   = 'is_active' in request.form
        db.commit()
        db.close()
        flash('Категория обновлена', 'success')
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('edit_category.html', category=category)

@app.route('/categories', methods=['GET'])
@login_required_role()
def get_categories_json():
    db = SessionLocal()
    categories = db.query(TicketCategory).filter(TicketCategory.is_active == True).all()
    result = [{"id": cat.id, "name": cat.name} for cat in categories]
    db.close()
    return jsonify(result)

@app.route('/ticket/<int:ticket_id>/change_category', methods=['POST'])
@login_required_role()
def change_ticket_category(ticket_id):
    db = SessionLocal()

    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return jsonify({"success": False, "error": "Заявка не найдена"}), 404

        category_id = request.form.get('category_id')
        if not category_id:
            return jsonify({"success": False, "error": "Категория не указана"}), 400

        category = db.query(TicketCategory).filter(TicketCategory.id == category_id).first()
        if not category:
            return jsonify({"success": False, "error": "Категория не найдена"}), 404

        old_category_name = "Не указана"
        if ticket.category_id:
            old_category = db.query(TicketCategory).filter(TicketCategory.id == ticket.category_id).first()
            if old_category:
                old_category_name = old_category.name

        ticket.category_id = category.id

        # Аудит изменения
        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="change_category",
            description=f"Изменена категория заявки #{ticket_id} с '{old_category_name}' на '{category.name}'",
            entity_type="ticket",
            entity_id=str(ticket_id),
            is_pdn_related=False,
            timestamp=datetime.datetime.utcnow()
        )
        db.add(audit_log)

        # Обновляем время изменения заявки
        ticket.updated_at = datetime.datetime.utcnow()
        db.commit()

        return jsonify({
            "success": True,
            "category_id": category.id,
            "category_name": category.name
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        db.close()

@app.route('/ticket/<int:ticket_id>/change_priority', methods=['POST'])
@login_required_role()
def change_ticket_priority(ticket_id):
    db = SessionLocal()

    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return jsonify({"success": False, "error": "Заявка не найдена"}), 404

        priority = request.form.get('priority')
        if not priority or priority not in ['low', 'normal', 'high']:
            return jsonify({"success": False, "error": "Некорректный приоритет"}), 400

        old_priority = ticket.priority
        ticket.priority = priority

        # Преобразование приоритета для аудита
        priority_names = {
            'low': 'Низкий',
            'normal': 'Средний',
            'high': 'Высокий'
        }

        # Аудит изменения
        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="change_priority",
            description=f"Изменен приоритет заявки #{ticket_id} с '{priority_names.get(old_priority, old_priority)}' на '{priority_names.get(priority, priority)}'",
            entity_type="ticket",
            entity_id=str(ticket_id),
            is_pdn_related=False,
            timestamp=datetime.datetime.utcnow()
        )
        db.add(audit_log)

        # Обновляем время изменения заявки
        ticket.updated_at = datetime.datetime.utcnow()
        db.commit()

        return jsonify({"success": True, "priority": priority})

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        db.close()

# Обновляем обработчик изменения статуса для отправки уведомлений
@app.route('/ticket/<int:ticket_id>/change_status', methods=['POST'])
@login_required_role()
def change_ticket_status(ticket_id):
    db = SessionLocal()
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        new_status = request.form.get('status')
        
        if not new_status:
            flash('Не указан новый статус', 'danger')
            return redirect(url_for('ticket_detail', ticket_id=ticket_id))
        
        # Сохраняем старый статус для логирования
        old_status = ticket.status
        
        # Обновляем статус
        ticket.status = new_status
        ticket.updated_at = datetime.datetime.utcnow()
        
        try:
            db.commit()
            
            # Логируем изменение статуса
            log_user_action(
                user_id=current_user.id,
                action_type='change_status',
                description=f"Изменен статус заявки #{ticket.id} ({ticket.title}): {old_status} → {new_status}"
            )
            
            # Отправляем уведомление
            message = f"Статус вашей заявки #{ticket.id} изменен на: {new_status}"
            notify_ticket_update(ticket, message, db, "status_change")
            
            flash('Статус заявки успешно обновлен', 'success')
        except Exception as e:
            db.rollback()
            flash(f'Ошибка при обновлении статуса: {str(e)}', 'danger')
        
        return redirect(url_for('ticket_detail', ticket_id=ticket_id))
    finally:
        db.close()

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        
        if not username or not password:
            flash('Пожалуйста, введите имя пользователя и пароль', 'error')
            return redirect(url_for('login'))
        
        db = SessionLocal()
        try:
            user = db.query(User).filter(User.username == username).first()
            
            if user and user.verify_password(password):
                if hasattr(user, 'is_fired') and user.is_fired:
                    flash('Ваша учетная запись деактивирована. Обратитесь к администратору.', 'error')
                    return redirect(url_for('login'))
                login_user(user)
                flash('Вы успешно вошли в систему', 'success')
                return redirect(url_for('dashboard'))
            else:
                flash('Неверное имя пользователя или пароль', 'error')
                return redirect(url_for('login'))
        finally:
            db.close()
    
    return render_template('login.html')

@app.route('/logout')
def logout():
    logout_user()
    flash('Вы вышли из системы', 'success')
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required_role()
def dashboard():
    ticket_db = SessionLocal()
    user_db = SessionLocal()
    statuses = STATUSES
    statuses_dict = {s['id']: s['name'] for s in statuses}

    user = user_db.query(User).filter(User.id == current_user.id).first()

    if not user:
        user_db.close()
        ticket_db.close()
        logout_user()
        flash('Пользовательская сессия недействительна. Пожалуйста, войдите снова.', 'error')
        return redirect(url_for('login'))

    total_tickets = ticket_db.query(func.count(Ticket.id)).scalar()
    new_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.status == 'open').scalar()
    resolved_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.status == 'resolved').scalar()

    assigned_tickets = ticket_db.query(func.count(Ticket.id)).filter(Ticket.assignee_id == current_user.id).scalar()

    thirty_days_ago = datetime.datetime.utcnow() - datetime.timedelta(days=30)
    resolved_this_month = ticket_db.query(func.count(Ticket.id)).filter(
        Ticket.assignee_id == current_user.id,
        Ticket.status == 'resolved',
        Ticket.updated_at >= thirty_days_ago
    ).scalar()

    twelve_hours_ago = datetime.datetime.utcnow() - datetime.timedelta(hours=12)
    recent_tickets = ticket_db.query(Ticket).filter(
        Ticket.created_at >= twelve_hours_ago
    ).order_by(desc(Ticket.created_at)).all()

    formatted_tickets = []
    for ticket in recent_tickets:
        creator = user_db.query(User).filter(User.chat_id == ticket.creator_chat_id).first()
        creator_name = creator.full_name if creator else "Неизвестный пользователь"
        description = ticket.description
        if len(description) > 100:
            description = description[:97] + "..."
        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'status': ticket.status,
            'created_at': ticket.created_at,
            'creator_name': creator_name,
            'description': description
        })

    dashboard_messages = ticket_db.query(DashboardMessage).order_by(DashboardMessage.created_at).all()

    for message in dashboard_messages:
        message.attachments = ticket_db.query(DashboardAttachment).filter(DashboardAttachment.message_id == message.id).all()

    pinned_message = ticket_db.query(DashboardMessage).filter(DashboardMessage.is_pinned == True).first()
    if pinned_message:
        pinned_message.attachments = ticket_db.query(DashboardAttachment).filter(DashboardAttachment.message_id == pinned_message.id).all()

    staff = user_db.query(User).filter(User.role.in_(['admin', 'curator'])).all()

    ticket_db.close()
    user_db.close()

    return render_template('dashboard.html',
                          total_tickets=total_tickets,
                          new_tickets=new_tickets,
                          resolved_tickets=resolved_tickets,
                          assigned_tickets=assigned_tickets,
                          resolved_this_month=resolved_this_month,
                          recent_tickets=formatted_tickets,
                          dashboard_messages=dashboard_messages,
                          pinned_message=pinned_message,
                          staff=staff,
                          current_user_id=current_user.id,
                          statuses=statuses,
                          statuses_dict=statuses_dict)

@app.route('/send_dashboard_message', methods=['POST'])
@login_required_role()
def send_dashboard_message():
    ticket_db = SessionLocal()

    try:
        message_content = request.form.get('message', '').strip()

        if not message_content and (('image' not in request.files) or not request.files['image'].filename):
            flash('Сообщение не может быть пустым', 'error')
            return redirect(url_for('dashboard'))

        new_message = DashboardMessage(
            sender_id=str(current_user.id),
            sender_name=current_user.full_name,
            content=message_content
        )

        ticket_db.add(new_message)
        ticket_db.commit()

        if 'image' in request.files and request.files['image'].filename:
            image_file = request.files['image']

            allowed_extensions = {'jpg', 'jpeg', 'png', 'gif', 'pdf', 'doc', 'docx', 'xls', 'xlsx', 'txt', 'ods', 'odt', 'csv', 'odp'}
            if '.' in image_file.filename and image_file.filename.rsplit('.', 1)[1].lower() in allowed_extensions:
                attachments_dir = os.path.join(app.config['UPLOAD_FOLDER'], 'dashboard')
                if not os.path.exists(attachments_dir):
                    os.makedirs(attachments_dir)

                filename = secure_filename(image_file.filename)
                filename = f"{datetime.datetime.utcnow().strftime('%Y%m%d%H%M%S')}_{filename}"

                file_path = os.path.join(attachments_dir, filename)
                image_file.save(file_path)

                file_type = image_file.content_type if hasattr(image_file, 'content_type') else None

                new_attachment = DashboardAttachment(
                    message_id=new_message.id,
                    file_path=os.path.join('dashboard', filename),
                    file_name=image_file.filename,
                    file_type=file_type
                )

                ticket_db.add(new_attachment)
                ticket_db.commit()
            else:
                flash('Недопустимый формат файла. Допустимые форматы: jpg, jpeg, png, gif', 'error')

        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="send_dashboard_message",
            description=f"Отправлено сообщение в командный чат",
            entity_type="dashboard_message",
            entity_id=str(new_message.id),
            is_pdn_related=False,
            timestamp=datetime.datetime.utcnow()
        )

        ticket_db.add(audit_log)
        ticket_db.commit()

        flash('Сообщение отправлено', 'success')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при отправке сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при отправке сообщения в командный чат: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/dashboard_attachment/<path:filename>')
@login_required_role()
def dashboard_attachment(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/ticket_attachment/<path:filename>')
@login_required_role()
def ticket_attachment(filename):
    return send_from_directory(app.config['UPLOAD_FOLDER'], filename)

@app.route('/pin_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role(role=['curator', 'admin'])
def pin_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        ticket_db.query(DashboardMessage).filter(DashboardMessage.is_pinned == True).update({'is_pinned': False})

        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()
        if message:
            message.is_pinned = True

            audit_log = AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type="pin_message",
                description=f"Закреплено сообщение в командном чате (ID: {message_id})",
                entity_type="dashboard_message",
                entity_id=str(message_id),
                is_pdn_related=False,
                timestamp=datetime.datetime.utcnow()
            )

            ticket_db.add(audit_log)
            ticket_db.commit()
            flash('Сообщение закреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при закреплении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при закреплении сообщения: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/unpin_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role(role=['curator', 'admin'])
def unpin_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()
        if message:
            message.is_pinned = False

            audit_log = AuditLog(
                actor_id=str(current_user.id),
                actor_name=current_user.full_name,
                action_type="unpin_message",
                description=f"Откреплено сообщение в командном чате (ID: {message_id})",
                entity_type="dashboard_message",
                entity_id=str(message_id),
                is_pdn_related=False,
                timestamp=datetime.datetime.utcnow()
            )

            ticket_db.add(audit_log)
            ticket_db.commit()
            flash('Сообщение откреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при откреплении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при откреплении сообщения: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/delete_dashboard_message/<int:message_id>', methods=['POST'])
@login_required_role()
def delete_dashboard_message(message_id):
    ticket_db = SessionLocal()

    try:
        message = ticket_db.query(DashboardMessage).filter(DashboardMessage.id == message_id).first()

        if not message:
            flash('Сообщение не найдено', 'error')
            return redirect(url_for('dashboard'))

        # Проверяем права доступа: пользователь может удалить свое сообщение или если он админ/куратор
        if str(message.sender_id) != str(current_user.id) and current_user.role not in ['admin', 'curator']:
            flash('У вас нет прав на удаление этого сообщения', 'error')
            return redirect(url_for('dashboard'))

        message_info = {
            'id': message.id,
            'sender_id': message.sender_id,
            'sender_name': message.sender_name,
            'content': message.content[:50] + ('...' if len(message.content) > 50 else '')
        }

        ticket_db.delete(message)

        audit_log = AuditLog(
            actor_id=str(current_user.id),
            actor_name=current_user.full_name,
            action_type="delete_dashboard_message",
            description=f"Удалено сообщение из командного чата (ID: {message_info['id']}, отправитель: {message_info['sender_name']})",
            entity_type="dashboard_message",
            entity_id=str(message_info['id']),
            is_pdn_related=False,
            timestamp=datetime.datetime.utcnow()
        )

        ticket_db.add(audit_log)
        ticket_db.commit()

        flash('Сообщение удалено', 'success')

    except Exception as e:
        ticket_db.rollback()
        flash(f'Ошибка при удалении сообщения: {str(e)}', 'error')
        logging.error(f"Ошибка при удалении сообщения из командного чата: {str(e)}")
    finally:
        ticket_db.close()

    return redirect(url_for('dashboard'))

@app.route('/create_category', methods=['GET', 'POST'])
@login_required_role(['curator'])
def create_category():
    db = SessionLocal()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        if not name:
            flash('Нужно указать название категории', 'error')
            db.close()
            return redirect(url_for('create_category'))
        new_cat = TicketCategory(name=name)
        db.add(new_cat)
        db.commit()
        flash(f'Категория "{name}" создана', 'success')
        db.close()
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('create_category.html')

@app.route('/send_chat_message', methods=['POST'])
@login_required_role()
def send_chat_message():
    db = SessionLocal()
    try:
        ticket_id = request.form.get('ticket_id')
        message_text = request.form.get('message')
        is_internal = request.form.get('is_internal') == 'true'

        if not ticket_id or not message_text:
            return jsonify({"success": False, "error": "Необходимо указать ID заявки и текст сообщения"}), 400

        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return jsonify({"success": False, "error": "Заявка не найдена"}), 404

        # Проверяем возможность комментирования
        if not ticket.can_be_commented():
            return jsonify({
                "success": False, 
                "error": f"Заявка находится в статусе '{ticket.get_status_display()}'. Комментирование недоступно."
            }), 403

        # Создаем новое сообщение
        new_message = Message(
            ticket_id=ticket_id,
            sender_id=str(current_user.id),
            sender_name=current_user.full_name,
            content=message_text,
            is_internal=is_internal
        )
        db.add(new_message)

        # Обрабатываем вложения
        if 'attachments[]' in request.files:
            files = request.files.getlist('attachments[]')
            for file in files:
                if file.filename:
                    filename = secure_filename(file.filename)
                    file_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
                    file.save(file_path)

                    # Определяем тип файла
                    file_type = file.content_type
                    is_image = file_type.startswith('image/')

                    # Создаем запись о вложении
                    attachment = Attachment(
                        ticket_id=ticket_id,
                        file_path=file_path,
                        file_name=filename,
                        file_type=file_type,
                        is_image=is_image,
                        message_id=new_message.id
                    )
                    db.add(attachment)

        # Обновляем время последнего обновления заявки
        ticket.updated_at = datetime.datetime.utcnow()
        db.commit()

        # Отправляем уведомление в Telegram
        notification_text = f"💬 <b>Новое сообщение в заявке #{ticket_id}</b>\n\n"
        notification_text += f"От: <b>{current_user.full_name}</b>\n"
        notification_text += f"Заявка: <b>{ticket.title}</b>\n"
        notification_text += f"Сообщение: {message_text}"

        notify_ticket_update(ticket, notification_text, db, "new_message")

        return jsonify({
            "success": True,
            "message": {
                "id": new_message.id,
                "content": new_message.content,
                "sender_name": new_message.sender_name,
                "is_internal": new_message.is_internal,
                "created_at": new_message.created_at.strftime('%d.%m.%Y %H:%M')
            }
        })

    except Exception as e:
        db.rollback()
        return jsonify({"success": False, "error": str(e)}), 500

    finally:
        db.close()

@app.route('/tickets')
@login_required_role()
def tickets():
    ticket_db = SessionLocal()
    user_db = SessionLocal()
    statuses = STATUSES
    statuses_dict = {s['id']: s['name'] for s in statuses}
    status = request.args.get('status', 'all')
    title = request.args.get('title', '')
    description = request.args.get('description', '')
    creator = request.args.get('creator_id', '')
    assignee = request.args.get('assignee_id', 'all')
    date_from = request.args.get('date_from', '')
    date_to = request.args.get('date_to', '')
    page = int(request.args.get('page', 1))
    per_page = 20

    query = ticket_db.query(Ticket)

    if status != 'all':
        query = query.filter(Ticket.status == status)

    if title:
        query = query.filter(Ticket.title.ilike(f'%{title}%'))

    if description:
        query = query.filter(Ticket.description.ilike(f'%{description}%'))

    if creator:
        query = query.filter(Ticket.creator_chat_id == creator)

    if assignee != 'all':
        if assignee == 'me':
            query = query.filter(Ticket.assignee_id == current_user.id)
        elif assignee == 'unassigned':
            query = query.filter(Ticket.assignee_id == None)
        else:
            query = query.filter(Ticket.assignee_id == assignee)

    if date_from:
        date_from_obj = datetime.datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(Ticket.created_at >= date_from_obj)

    if date_to:
        date_to_obj = datetime.datetime.strptime(date_to, '%Y-%m-%d')
        date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(Ticket.created_at <= date_to_obj)

    categories = {cat.id: cat.name for cat in ticket_db.query(TicketCategory).all()}

    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page

    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    tickets_query = query.order_by(desc(Ticket.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    all_staff = user_db.query(User).all()
    staff_map = {str(staff.id): staff.full_name for staff in all_staff}
    creator_map = {staff.chat_id: staff.full_name for staff in all_staff if staff.chat_id}

    formatted_tickets = []
    for ticket in tickets_query:
        creator_name = creator_map.get(ticket.creator_chat_id, "Неизвестный пользователь")
        assignee_name = staff_map.get(str(ticket.assignee_id), "-") if ticket.assignee_id else "-"
        category_name = categories.get(ticket.category_id, "-") if ticket.category_id else "-"

        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'creator_name': creator_name,
            'assignee': assignee_name,
            'category_name': category_name,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at
        })

    filter_params = {
        'status': status,
        'title': title,
        'description': description,
        'creator': creator,
        'assignee': assignee,
        'date_from': date_from,
        'date_to': date_to
    }

    ticket_db.close()
    user_db.close()

    return render_template('tickets.html',
                          tickets=formatted_tickets,
                          all_staff=all_staff,
                          filter_params=filter_params,
                          page=page,
                          total_pages=total_pages,
                          has_prev=(page > 1),
                          has_next=(page < total_pages),
                          statuses=statuses,
                          statuses_dict=statuses_dict)

@app.route('/tickets/fragment', methods=['POST'])
@login_required_role()
def tickets_fragment():
    ticket_db = SessionLocal()
    user_db = SessionLocal()
    statuses = STATUSES
    statuses_dict = {s['id']: s['name'] for s in statuses}
    status = request.form.get('status', 'all')
    title = request.form.get('title', '')
    description = request.form.get('description', '')
    creator = request.form.get('creator_id', '')
    assignee = request.form.get('assignee_id', 'all')
    date_from = request.form.get('date_from', '')
    date_to = request.form.get('date_to', '')
    page = int(request.form.get('page', 1))
    per_page = 20

    query = ticket_db.query(Ticket)

    if status != 'all':
        query = query.filter(Ticket.status == status)

    if title:
        query = query.filter(Ticket.title.ilike(f'%{title}%'))

    if description:
        query = query.filter(Ticket.description.ilike(f'%{description}%'))

    if creator:
        query = query.filter(Ticket.creator_chat_id == creator)

    if assignee != 'all':
        if assignee == 'me':
            query = query.filter(Ticket.assignee_id == current_user.id)
        elif assignee == 'unassigned':
            query = query.filter(Ticket.assignee_id == None)
        else:
            query = query.filter(Ticket.assignee_id == assignee)

    if date_from:
        date_from_obj = datetime.datetime.strptime(date_from, '%Y-%m-%d')
        query = query.filter(Ticket.created_at >= date_from_obj)

    if date_to:
        date_to_obj = datetime.datetime.strptime(date_to, '%Y-%m-%d')
        date_to_obj = date_to_obj.replace(hour=23, minute=59, second=59)
        query = query.filter(Ticket.created_at <= date_to_obj)

    categories = {cat.id: cat.name for cat in ticket_db.query(TicketCategory).all()}

    total_count = query.count()
    total_pages = (total_count + per_page - 1) // per_page

    if page < 1:
        page = 1
    elif page > total_pages and total_pages > 0:
        page = total_pages

    tickets_query = query.order_by(desc(Ticket.created_at)).offset((page - 1) * per_page).limit(per_page).all()

    all_staff = user_db.query(User).all()
    staff_map = {str(staff.id): staff.full_name for staff in all_staff}
    creator_map = {staff.chat_id: staff.full_name for staff in all_staff if staff.chat_id}

    formatted_tickets = []
    for ticket in tickets_query:
        creator_name = creator_map.get(ticket.creator_chat_id, "Неизвестный пользователь")
        assignee_name = staff_map.get(str(ticket.assignee_id), "-") if ticket.assignee_id else "-"
        category_name = categories.get(ticket.category_id, "-") if ticket.category_id else "-"

        formatted_tickets.append({
            'id': ticket.id,
            'title': ticket.title,
            'creator_name': creator_name,
            'assignee': assignee_name,
            'category_name': category_name,
            'status': ticket.status,
            'priority': ticket.priority,
            'created_at': ticket.created_at
        })

    ticket_db.close()
    user_db.close()

    return render_template('includes/tickets_table_fragment.html',
                          tickets=formatted_tickets,
                          page=page,
                          total_pages=total_pages,
                          has_prev=(page > 1),
                          has_next=(page < total_pages),
                          statuses=statuses,
                          statuses_dict=statuses_dict)

@app.route('/users', methods=['GET', 'POST'])
@login_required
def users():
    if current_user.role not in ['admin', 'curator']:
        flash('У вас нет доступа к этой странице', 'error')
        return redirect(url_for('index'))
    
    db = SessionLocal()
    ticket_db = SessionLocal()
    try:
        if request.method == 'POST':
            user_id = request.form.get('user_id', type=int)
            action = request.form.get('action')
            
            if user_id and action:
                user = db.get(User, user_id)
                if not user:
                    flash('Пользователь не найден', 'error')
                    return redirect(url_for('users'))
                
                if action == 'activate':
                    user.is_active = True
                    flash(f'Пользователь {user.full_name} активирован', 'success')
                    audit_action = 'activate_user'
                elif action == 'deactivate':
                    user.is_active = False
                    flash(f'Пользователь {user.full_name} деактивирован', 'info')
                    audit_action = 'deactivate_user'
                
                # Добавляем запись в лог
                ticket_db.add(AuditLog(
                    actor_id=str(current_user.id),
                    actor_name=current_user.full_name,
                    action_type=audit_action,
                    description=f"{audit_action} для пользователя {user.full_name} (id={user_id})",
                    entity_type='user',
                    entity_id=str(user_id),
                    is_pdn_related=True,
                    timestamp=datetime.datetime.utcnow()
                ))
                
                db.commit()
                ticket_db.commit()
                return redirect(url_for('users'))
        
        # Получаем всех пользователей
        users = db.query(User).all()
        
        # Загружаем связанные объекты для каждого пользователя
        for user in users:
            if user.position_id:
                _ = user.position
            if user.office_id:
                _ = user.office
        
        # Получаем историю действий
        actor_id = request.args.get('actor_id', '').strip()
        action_type = request.args.get('action_type', '').strip()
        date_from = request.args.get('date_from', '').strip()
        date_to = request.args.get('date_to', '').strip()
        
        actions_query = ticket_db.query(AuditLog).filter(AuditLog.entity_type == 'user')
        if actor_id:
            actions_query = actions_query.filter(AuditLog.actor_id == actor_id)
        if action_type:
            actions_query = actions_query.filter(AuditLog.action_type == action_type)
        if date_from:
            from_dt = datetime.datetime.strptime(date_from, '%Y-%m-%d')
            actions_query = actions_query.filter(AuditLog.timestamp >= from_dt)
        if date_to:
            to_dt = datetime.datetime.strptime(date_to, '%Y-%m-%d')
            to_dt = to_dt.replace(hour=23, minute=59, second=59)
            actions_query = actions_query.filter(AuditLog.timestamp <= to_dt)
        
        actions = actions_query.order_by(AuditLog.timestamp.desc()).limit(200).all()
        
        # Для фильтров
        all_actors = ticket_db.query(AuditLog.actor_id, AuditLog.actor_name).distinct().all()
        all_action_types = [row[0] for row in ticket_db.query(AuditLog.action_type).distinct().all()]
        
        # Словари для отображения действий
        action_type_labels = {
            'approve_registration': 'Подтверждение регистрации',
            'reject_registration': 'Отклонение регистрации',
            'activate_user': 'Активация пользователя',
            'deactivate_user': 'Деактивация пользователя'
        }
        
        action_type_colors = {
            'approve_registration': 'success',
            'reject_registration': 'danger',
            'activate_user': 'success',
            'deactivate_user': 'warning'
        }
        
        return render_template('users.html',
                             users=users,
                             actions=actions,
                             all_actors=all_actors,
                             all_action_types=all_action_types,
                             action_type_labels=action_type_labels,
                             action_type_colors=action_type_colors,
                             filter_params={
                                 'actor_id': actor_id,
                                 'action_type': action_type,
                                 'date_from': date_from,
                                 'date_to': date_to
                             })
    finally:
        db.close()
        ticket_db.close()

@app.route('/create_user', methods=['GET', 'POST'])
@login_required_role(['curator'])
def create_user():
    db = SessionLocal()
    try:
        # Получаем данные для выпадающих списков
        departments = db.query(Department).all()
        positions = db.query(Position).all()
        offices = db.query(Office).all()

        if request.method == 'POST':
            username = request.form.get('username', '').strip()
            full_name = request.form.get('full_name', '').strip()
            email = request.form.get('email', '').strip()
            phone = request.form.get('phone', '').strip()
            chat_id = request.form.get('chat_id')
            position_id = request.form.get('position_id')
            department_id = request.form.get('department_id')
            office_id = request.form.get('office_id')
            password = request.form.get('password', '').strip()
            
            # Проверяем, не существует ли уже пользователь с таким логином
            existing_user = db.query(User).filter(User.username == username).first()
            if existing_user:
                flash('Пользователь с таким логином уже существует', 'error')
                return redirect(url_for('create_user'))
            
            # Создаем нового пользователя с ролью 'user'
            new_user = User(
                username=username,
                full_name=full_name,
                email=email if email else None,
                phone=phone if phone else None,
                chat_id=chat_id if chat_id else None,
                position_id=position_id if position_id else None,
                department_id=department_id if department_id else None,
                office_id=office_id if office_id else None,
                role='user',  # Всегда создаем с ролью 'user'
                is_active=True,
                is_confirmed=True
            )
            new_user.set_password(password)
            
            db.add(new_user)
            db.commit()
            
            flash('Пользователь успешно создан', 'success')
            return redirect(url_for('users'))
    except Exception as e:
        db.rollback()
        flash(f'Ошибка при создании пользователя: {str(e)}', 'error')
    finally:
        db.close()
        
    return render_template('create_user.html', 
                         departments=departments,
                         positions=positions,
                         offices=offices)

@app.route('/ticket/<int:ticket_id>')
@login_required_role()
def ticket_detail(ticket_id):
    db = SessionLocal()
    statuses = STATUSES
    statuses_dict = {s['id']: s['name'] for s in statuses}
    ticket = db.query(Ticket)\
        .options(
            joinedload(Ticket.attachments),
            joinedload(Ticket.messages)
        )\
        .filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    creator = db.query(User).filter(User.chat_id == ticket.creator_chat_id).first()
    assignee = db.query(User).filter(User.id == ticket.assignee_id).first() if ticket.assignee_id else None
    category = db.query(TicketCategory).filter(TicketCategory.id == ticket.category_id).first() if ticket.category_id else None
    staff = db.query(User).filter(User.role.in_(['admin', 'curator'])).all()

    # Разделяем сообщения на внешние и внутренние и сортируем их
    external_messages = sorted([msg for msg in ticket.messages if not msg.is_internal],
                             key=lambda x: x.created_at)
    internal_messages = sorted([msg for msg in ticket.messages if msg.is_internal],
                             key=lambda x: x.created_at)

    # Вложения к заявке (без message_id)
    ticket_attachments = [att for att in ticket.attachments if att.message_id is None]
    # Для каждого сообщения добавляем attachments
    for msg in ticket.messages:
        msg.attachments = [att for att in ticket.attachments if att.message_id == msg.id]

    categories = db.query(TicketCategory).filter(TicketCategory.is_active == True).all()
    response = render_template('ticket_detail.html',
                             ticket=ticket,
                             creator_name=creator.full_name if creator else 'Неизвестно',
                             assignee=assignee,
                             category=category,
                             staff=staff,
                             categories=categories,
                             external_messages=external_messages,
                             internal_messages=internal_messages,
                             ticket_attachments=ticket_attachments,
                             statuses=statuses,
                             statuses_dict=statuses_dict)
    db.close()
    return response

@app.route('/ticket/<int:ticket_id>/assign', methods=['POST'])
@login_required_role()
def assign_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    assignee_id = request.form.get('assignee_id')
    if assignee_id:
        ticket.assignee_id = int(assignee_id)
        db.commit()
        flash('Исполнитель назначен', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/resolve', methods=['POST'])
@login_required_role()
def resolve_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    resolution = request.form.get('resolution')
    if resolution:
        ticket.resolution = resolution
        ticket.status = 'resolved'
        db.commit()
        flash('Заявка завершена', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/reopen', methods=['POST'])
@login_required_role()
def reopen_ticket(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    reason = request.form.get('reason')
    if reason:
        ticket.resolution = None
        ticket.status = 'in_progress'
        db.commit()
        flash('Заявка возвращена в работу', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/irrelevant', methods=['POST'])
@login_required_role()
def mark_irrelevant(ticket_id):
    db = SessionLocal()
    ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
    if not ticket:
        db.close()
        flash('Заявка не найдена', 'error')
        return redirect(url_for('tickets'))
    reason = request.form.get('reason')
    if reason:
        ticket.resolution = reason
        ticket.status = 'irrelevant'
        db.commit()
        flash('Заявка отмечена как неактуальная', 'success')
    db.close()
    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/message/<int:message_id>/pin/<chat_type>', methods=['POST'])
@login_required_role()
def pin_message(ticket_id, message_id, chat_type):
    db = SessionLocal()
    try:
        # Сначала открепляем все сообщения в этом чате
        if chat_type == 'external':
            db.query(Message).filter(
                Message.ticket_id == ticket_id,
                Message.is_internal == False
            ).update({'is_pinned': False})
        else:
            db.query(Message).filter(
                Message.ticket_id == ticket_id,
                Message.is_internal == True
            ).update({'is_pinned': False})

        # Закрепляем выбранное сообщение
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.ticket_id == ticket_id
        ).first()

        if message:
            message.is_pinned = True
            db.commit()
            flash('Сообщение закреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        db.rollback()
        flash(f'Ошибка при закреплении сообщения: {str(e)}', 'error')
    finally:
        db.close()

    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

@app.route('/ticket/<int:ticket_id>/message/<int:message_id>/unpin/<chat_type>', methods=['POST'])
@login_required_role()
def unpin_message(ticket_id, message_id, chat_type):
    db = SessionLocal()
    try:
        message = db.query(Message).filter(
            Message.id == message_id,
            Message.ticket_id == ticket_id
        ).first()

        if message:
            message.is_pinned = False
            db.commit()
            flash('Сообщение откреплено', 'success')
        else:
            flash('Сообщение не найдено', 'error')

    except Exception as e:
        db.rollback()
        flash(f'Ошибка при откреплении сообщения: {str(e)}', 'error')
    finally:
        db.close()

    return redirect(url_for('ticket_detail', ticket_id=ticket_id))

# API endpoints для обновления полей заявки
@app.route('/api/ticket/<int:ticket_id>/update', methods=['POST'])
@login_required_role()
def update_ticket_field(ticket_id):
    db = SessionLocal()
    try:
        ticket = db.query(Ticket).filter(Ticket.id == ticket_id).first()
        if not ticket:
            return jsonify({'success': False, 'message': 'Заявка не найдена'}), 404

        # Проверяем, можно ли изменять заявку
        if ticket.status in ['resolved', 'irrelevant', 'closed']:
            return jsonify({'success': False, 'message': 'Нельзя изменять завершенную заявку'}), 400

        data = request.get_json()
        field = data.get('field')
        value = data.get('value')

        if field == 'priority':
            if value not in ['low', 'normal', 'high']:
                return jsonify({'success': False, 'message': 'Неверный приоритет'}), 400
            ticket.priority = value

        elif field == 'status':
            if value not in ['open', 'closed', 'irrelevant']:
                return jsonify({'success': False, 'message': 'Неверный статус'}), 400
            ticket.status = value

        elif field == 'assignee':
            if value:
                user = db.query(User).filter(User.id == value).first()
                if not user:
                    return jsonify({'success': False, 'message': 'Пользователь не найден'}), 400
                ticket.assignee_id = value
            else:
                ticket.assignee_id = None

        else:
            return jsonify({'success': False, 'message': 'Неизвестное поле'}), 400

        ticket.updated_at = datetime.datetime.utcnow()
        db.commit()

        # Логируем изменение
        log_entry = AuditLog(
            actor_id=current_user.chat_id,
            actor_name=current_user.full_name,
            action_type='update',
            description=f'Изменено поле {field} заявки #{ticket_id} на значение {value}',
            entity_type='ticket',
            entity_id=str(ticket_id)
        )
        db.add(log_entry)
        db.commit()

        return jsonify({'success': True, 'message': 'Поле обновлено'})

    except Exception as e:
        db.rollback()
        return jsonify({'success': False, 'message': str(e)}), 500
    finally:
        db.close()

@app.route('/api/ticket/<int:ticket_id>/status', methods=['POST'])
@login_required_role()
def change_ticket_status_api(ticket_id):
    db = SessionLocal()
    try:
        ticket = Ticket.query.get_or_404(ticket_id)
        data = request.get_json()
        
        if not data or 'status' not in data:
            return jsonify({"success": False, "error": "Не указан новый статус"}), 400
        
        new_status = data['status']
        reason = data.get('reason', '')
        
        # Сохраняем старый статус для логирования
        old_status = ticket.status
        
        # Обновляем статус
        ticket.status = new_status
        ticket.resolution = reason if new_status in ['closed', 'irrelevant'] else None
        ticket.updated_at = datetime.datetime.utcnow()
        
        try:
            # Если добавили причину, добавляем сообщение в чат
            if reason:
                # Внутреннее сообщение для администраторов
                new_message = Message(
                    ticket_id=ticket_id,
                    sender_id=str(current_user.id),
                    sender_name=current_user.full_name,
                    content=f"Статус изменен на '{new_status}'\nПричина: {reason}",
                    is_internal=True
                )
                db.add(new_message)
                
                # Внешнее сообщение для пользователя
                user_message = Message(
                    ticket_id=ticket_id,
                    sender_id=str(current_user.id),
                    sender_name=current_user.full_name,
                    content=f"Статус заявки изменен на '{new_status}'\nКомментарий: {reason}",
                    is_internal=False
                )
                db.add(user_message)
            
            db.commit()
            
            # Логируем изменение статуса
            log_user_action(
                user_id=current_user.id,
                action_type='change_status',
                description=f"Изменен статус заявки #{ticket.id} ({ticket.title}): {old_status} → {new_status}" + (f"\nПричина: {reason}" if reason else "")
            )
            
            # Отправляем уведомление
            notification_text = f"🔔 <b>Изменен статус заявки #{ticket_id}</b>\n\n"
            notification_text += f"Заявка: <b>{ticket.title}</b>\n"
            notification_text += f"Статус: <b>{new_status}</b>\n"
            if reason:
                notification_text += f"Комментарий: {reason}\n"
            
            notify_ticket_update(ticket, notification_text, db, "status_change")
            
            return jsonify({"success": True, "status": new_status})
        except Exception as e:
            db.rollback()
            return jsonify({"success": False, "error": str(e)}), 500
    finally:
        db.close()

# Добавляем функцию now() в контекст шаблона
@app.context_processor
def utility_processor():
    return {
        'now': datetime.datetime.utcnow
    }

@app.route('/dictionaries')
@login_required_role()
def dictionaries():
    db = SessionLocal()
    try:
        # --- Фильтрация отделений ---
        dep_search = request.args.get('dep_search', '').strip()
        dep_query = db.query(Department)
        if dep_search:
            dep_query = dep_query.filter(Department.name.ilike(f'%{dep_search}%'))
        departments = dep_query.all()

        # --- Фильтрация кабинетов ---
        office_search = request.args.get('office_search', '').strip()
        office_dep_filter = request.args.get('office_dep_filter', '').strip()
        office_query = db.query(Office)
        if office_search:
            office_query = office_query.filter(Office.name.ilike(f'%{office_search}%'))
        if office_dep_filter:
            office_query = office_query.filter(Office.department_id == int(office_dep_filter))
        offices = office_query.all()
        
        # Загружаем связанные объекты для всех кабинетов
        for office in offices:
            if office.department_id:
                office.department = db.query(Department).get(office.department_id)
        
        all_departments = db.query(Department).all()

        # --- Фильтрация должностей ---
        pos_search = request.args.get('pos_search', '').strip()
        pos_query = db.query(Position)
        if pos_search:
            pos_query = pos_query.filter(Position.name.ilike(f'%{pos_search}%'))
        positions = pos_query.all()

        # --- Фильтрация категорий ---
        cat_search = request.args.get('cat_search', '').strip()
        cat_query = db.query(TicketCategory)
        if cat_search:
            cat_query = cat_query.filter(TicketCategory.name.ilike(f'%{cat_search}%'))
        categories = cat_query.all()

        return render_template('dictionaries.html',
                             departments=departments,
                             offices=offices,
                             positions=positions,
                             categories=categories,
                             all_departments=all_departments)
    finally:
        db.close()

@app.route('/add_department', methods=['GET', 'POST'])
@login_required_role()
def add_department():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            active_from = None
            
        if active_to:
            active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            active_to = None
            
        db = SessionLocal()
        dep = Department(name=name, active_from=active_from, active_to=active_to)
        dep.update_active_status()  # Обновляем статус активности
        db.add(dep)
        db.commit()
        db.close()
        flash('Отделение добавлено', 'success')
        return redirect(url_for('dictionaries'))
    return render_template('edit_department.html', dep=None)

@app.route('/edit_department/<int:dep_id>', methods=['GET', 'POST'])
@login_required_role()
def edit_department(dep_id):
    db = SessionLocal()
    dep = db.query(Department).get(dep_id)
    if not dep:
        db.close()
        abort(404)
    if request.method == 'POST':
        dep.name = request.form.get('name', '').strip()
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            dep.active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            dep.active_from = None
            
        if active_to:
            dep.active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            dep.active_to = None
            
        dep.update_active_status()  # Обновляем статус активности
        db.commit()
        db.close()
        flash('Отделение обновлено', 'success')
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('edit_department.html', dep=dep)

@app.route('/delete_department/<int:dep_id>')
@login_required_role()
def delete_department(dep_id):
    db = SessionLocal()
    dep = db.query(Department).get(dep_id)
    if dep:
        db.delete(dep)
        db.commit()
        flash('Отделение удалено', 'success')
    db.close()
    return redirect(url_for('dictionaries'))

@app.route('/add_office', methods=['GET', 'POST'])
@login_required_role()
def add_office():
    db = SessionLocal()
    departments = db.query(Department).all()
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        department_id = request.form.get('department_id')
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            active_from = None
            
        if active_to:
            active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            active_to = None
            
        office = Office(
            name=name,
            department_id=department_id if department_id else None,
            active_from=active_from,
            active_to=active_to
        )
        office.update_active_status()  # Обновляем статус активности
        db.add(office)
        db.commit()
        db.close()
        flash('Кабинет добавлен', 'success')
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('edit_office.html', office=None, departments=departments)

@app.route('/edit_office/<int:office_id>', methods=['GET', 'POST'])
@login_required_role()
def edit_office(office_id):
    db = SessionLocal()
    office = db.query(Office).get(office_id)
    if not office:
        db.close()
        abort(404)
    departments = db.query(Department).all()
    if request.method == 'POST':
        office.name = request.form.get('name', '').strip()
        office.department_id = request.form.get('department_id')
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            office.active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            office.active_from = None
            
        if active_to:
            office.active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            office.active_to = None
            
        office.update_active_status()  # Обновляем статус активности
        db.commit()
        db.close()
        flash('Кабинет обновлен', 'success')
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('edit_office.html', office=office, departments=departments)

@app.route('/delete_office/<int:office_id>')
@login_required_role()
def delete_office(office_id):
    db = SessionLocal()
    office = db.query(Office).get(office_id)
    if office:
        db.delete(office)
        db.commit()
        flash('Кабинет удалён', 'success')
    db.close()
    return redirect(url_for('dictionaries'))

@app.route('/add_position', methods=['GET', 'POST'])
@login_required_role()
def add_position():
    if request.method == 'POST':
        name = request.form.get('name', '').strip()
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            active_from = None
            
        if active_to:
            active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            active_to = None
            
        db = SessionLocal()
        pos = Position(name=name, active_from=active_from, active_to=active_to)
        pos.update_active_status()  # Обновляем статус активности
        db.add(pos)
        db.commit()
        db.close()
        flash('Должность добавлена', 'success')
        return redirect(url_for('dictionaries'))
    return render_template('edit_position.html', pos=None)

@app.route('/edit_position/<int:pos_id>', methods=['GET', 'POST'])
@login_required_role()
def edit_position(pos_id):
    db = SessionLocal()
    pos = db.query(Position).get(pos_id)
    if not pos:
        db.close()
        abort(404)
    if request.method == 'POST':
        pos.name = request.form.get('name', '').strip()
        
        # Преобразуем строковые даты в объекты datetime
        active_from = request.form.get('active_from')
        active_to = request.form.get('active_to')
        
        if active_from:
            pos.active_from = datetime.datetime.strptime(active_from, '%Y-%m-%d')
        else:
            pos.active_from = None
            
        if active_to:
            pos.active_to = datetime.datetime.strptime(active_to, '%Y-%m-%d')
        else:
            pos.active_to = None
            
        pos.update_active_status()  # Обновляем статус активности
        db.commit()
        db.close()
        flash('Должность обновлена', 'success')
        return redirect(url_for('dictionaries'))
    db.close()
    return render_template('edit_position.html', pos=pos)

@app.route('/delete_position/<int:pos_id>')
@login_required_role()
def delete_position(pos_id):
    db = SessionLocal()
    pos = db.query(Position).get(pos_id)
    if pos:
        db.delete(pos)
        db.commit()
        flash('Должность удалена', 'success')
    db.close()
    return redirect(url_for('dictionaries'))

@app.route('/delete_category/<int:category_id>')
@login_required_role(['curator'])
def delete_category(category_id):
    db = SessionLocal()
    category = db.query(TicketCategory).get(category_id)
    if category:
        db.delete(category)
        db.commit()
        flash('Категория удалена', 'success')
    db.close()
    return redirect(url_for('dictionaries'))

@app.template_filter('datetime_msk')
def format_datetime_msk(value, fmt='%d.%m.%Y %H:%M'):
    if value is None:
        return ''
    # Если value — naive datetime, делаем его aware в UTC
    if value.tzinfo is None:
        value = utc.localize(value)
    msk = timezone('Europe/Moscow')
    return value.astimezone(msk).strftime(fmt)

if __name__ == '__main__':
    debug_mode = os.getenv("DEBUG", "False").lower() in ("true", "1", "t")
    app.run(host='0.0.0.0', port=5000, debug=debug_mode)
