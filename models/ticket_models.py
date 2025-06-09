from sqlalchemy import Column, Integer, String, DateTime, Text, ForeignKey, Boolean
from sqlalchemy.orm import relationship
import datetime
from models.db_init import Base
from models.user_models import User

class TicketCategory(Base):
    __tablename__ = "ticket_categories"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False, unique=True)
    description = Column(Text, nullable=True)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    is_active = Column(Boolean, default=True)

    # Relationship with Ticket
    tickets = relationship("Ticket", back_populates="category")

class Ticket(Base):
    __tablename__ = "tickets"

    id = Column(Integer, primary_key=True, index=True)
    title = Column(String(100), nullable=False)
    description = Column(Text, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    updated_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc), onupdate=lambda: datetime.datetime.now(datetime.timezone.utc))
    status = Column(String(20), default="new")  # new, in_progress, resolved, closed, irrelevant
    creator_chat_id = Column(String(50), nullable=False)
    assignee_id = Column(Integer, ForeignKey("users.id"), nullable=True)  # Ссылка на пользователя-исполнителя
    resolution = Column(Text, nullable=True)  # Текст решения заявки

    # Новые поля
    category_id = Column(Integer, ForeignKey("ticket_categories.id"), nullable=True)
    priority = Column(String(20), default="normal")  # low, normal, high

    # Relationships
    category = relationship("TicketCategory", back_populates="tickets")
    assignee = relationship(User, foreign_keys=[assignee_id])

    # Relationship with Attachment
    attachments = relationship("Attachment", back_populates="ticket", cascade="all, delete-orphan")

    # Relationship with Message
    messages = relationship("Message", back_populates="ticket", cascade="all, delete-orphan")

class Attachment(Base):
    __tablename__ = "attachments"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    file_path = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=True)
    upload_date = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    is_image = Column(Boolean, default=False)  # Flag to identify image files
    message_id = Column(Integer, ForeignKey("messages.id"), nullable=True)  # Optional link to a specific message

    # Relationship with Ticket
    ticket = relationship("Ticket", back_populates="attachments")

class Message(Base):
    __tablename__ = "messages"

    id = Column(Integer, primary_key=True, index=True)
    ticket_id = Column(Integer, ForeignKey("tickets.id"))
    sender_id = Column(String(50), nullable=False)  # ID пользователя или 'system' для системных сообщений
    sender_name = Column(String(100), nullable=False)  # Имя отправителя
    content = Column(Text, nullable=False)  # Содержимое сообщения
    is_from_user = Column(Boolean, default=False)  # Сообщение от пользователя (true) или от администратора (false)
    is_internal = Column(Boolean, default=False)  # Внутреннее сообщение (true) - только для админов, (false) - видно всем
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    is_pinned = Column(Boolean, default=False)  # Закрепленное сообщение

    # Relationship with Ticket
    ticket = relationship("Ticket", back_populates="messages")

    # Relationship with Attachment
    attachments = relationship("Attachment", backref="message")

class AuditLog(Base):
    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, index=True)
    actor_id = Column(String(50), nullable=False)  # ID пользователя, выполнившего действие (chat_id)
    actor_name = Column(String(100), nullable=True)  # Имя пользователя (для удобства чтения)
    action_type = Column(String(50), nullable=False)  # Тип действия (create, update, delete, login, etc.)
    description = Column(Text, nullable=False)  # Описание действия
    entity_type = Column(String(50), nullable=True)  # Тип сущности (user, ticket, etc.)
    entity_id = Column(String(50), nullable=True)  # ID сущности, связанной с действием
    timestamp = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))  # Время действия
    is_pdn_related = Column(Boolean, default=False)  # Связано ли с обработкой ПДн (для аудита по 152-ФЗ)
    ip_address = Column(String(50), nullable=True)  # IP-адрес пользователя
    details = Column(Text, nullable=True)  # Дополнительные детали (JSON или текст)

class DashboardMessage(Base):
    __tablename__ = "dashboard_messages"

    id = Column(Integer, primary_key=True, index=True)
    sender_id = Column(String(50), nullable=False)  # ID пользователя
    sender_name = Column(String(100), nullable=False)  # Имя отправителя
    content = Column(Text, nullable=False)  # Содержимое сообщения
    created_at = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))
    is_pinned = Column(Boolean, default=False)  # Закрепленное сообщение

    # Relationship with DashboardAttachment
    attachments = relationship("DashboardAttachment", back_populates="message", cascade="all, delete-orphan")

class DashboardAttachment(Base):
    __tablename__ = "dashboard_attachments"

    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(Integer, ForeignKey("dashboard_messages.id"))
    file_path = Column(String(255), nullable=False)
    file_name = Column(String(255), nullable=False)
    file_type = Column(String(50), nullable=True)
    upload_date = Column(DateTime, default=lambda: datetime.datetime.now(datetime.timezone.utc))

    # Relationship with DashboardMessage
    message = relationship("DashboardMessage", back_populates="attachments")