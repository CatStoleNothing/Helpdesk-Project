from sqlalchemy import Column, Integer, String, DateTime, Boolean
import datetime
from passlib.context import CryptContext
from models.db_init import Base
import logging

# Suppress passlib bcrypt warning
logging.getLogger("passlib.handlers.bcrypt").setLevel(logging.ERROR)

# Password hashing config
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


class User(Base):
    __tablename__ = "users"

    id = Column(Integer, primary_key=True, index=True)
    username = Column(String(50), unique=True, nullable=True)
    password_hash = Column(String(100), nullable=True)
    full_name = Column(String(100), nullable=False)
    position = Column(String(100), nullable=True)
    department = Column(String(100), nullable=True)
    office = Column(String(100), nullable=True)
    # Добавляем новые поля
    phone = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    privacy_consent = Column(Boolean, default=False)
    consent_date = Column(DateTime, nullable=True)
    is_archived = Column(Boolean, default=False)  # Для пометки уволенных сотрудников
    is_confirmed = Column(Boolean, default=False)  # Флаг подтверждения регистрации админом
    # Конец новых полей
    chat_id = Column(String(50), unique=True, nullable=False)
    role = Column(String(20), default="agent")  # agent, admin, curator
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Method to verify password
    def verify_password(self, plain_password):
        if not self.password_hash:
            return False
        return pwd_context.verify(plain_password, self.password_hash)

    # Method to get password hash
    @staticmethod
    def get_password_hash(password):
        return pwd_context.hash(password)

    # Flask-Login compatibility: return primary key as string
    def get_id(self):
        return str(self.id)

    # Flask-Login compatibility property
    @property
    def is_authenticated(self):
        return True
