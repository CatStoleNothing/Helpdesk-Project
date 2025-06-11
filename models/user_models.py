from sqlalchemy import Column, Integer, String, DateTime, Boolean, ForeignKey, Date, Text
from sqlalchemy.orm import relationship
import datetime
from passlib.context import CryptContext
from models.db_init import Base
import logging
from models.department_models import Department
from models.position_models import Position
from models.office_models import Office

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
    position_id = Column(Integer, ForeignKey("positions.id"), nullable=True)
    office_id = Column(Integer, ForeignKey("offices.id"), nullable=True)
    department_id = Column(Integer, ForeignKey("departments.id"), nullable=True)
    # Добавляем новые поля
    phone = Column(String(20), nullable=True)
    email = Column(String(100), nullable=True)
    privacy_consent = Column(Boolean, default=False)
    consent_date = Column(DateTime, nullable=True)
    is_archived = Column(Boolean, default=False)  # Для пометки уволенных сотрудников
    archived_at = Column(Date, nullable=True)  # Дата увольнения
    is_confirmed = Column(Boolean, default=False)  # Флаг подтверждения регистрации админом
    # Поля для отслеживания подтверждения/отклонения
    approved_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    approved_at = Column(DateTime, nullable=True)
    rejected_by_id = Column(Integer, ForeignKey("users.id"), nullable=True)
    rejected_at = Column(DateTime, nullable=True)
    rejection_reason = Column(Text, nullable=True)
    # Конец новых полей
    chat_id = Column(String(50), unique=True, nullable=False)
    role = Column(String(20), default="agent")  # agent, admin, curator
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, onupdate=datetime.datetime.utcnow)
    is_active = Column(Boolean, default=True)

    # Relationships
    position = relationship("Position", back_populates="users")
    office = relationship("Office", back_populates="users")
    department = relationship("Department", back_populates="users")
    approved_by = relationship("User", foreign_keys=[approved_by_id], remote_side=[id])
    rejected_by = relationship("User", foreign_keys=[rejected_by_id], remote_side=[id])

    def set_password(self, password):
        """Устанавливает хеш пароля для пользователя"""
        self.password_hash = pwd_context.hash(password)

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

    @property
    def is_fired(self):
        """Пользователь считается уволенным, если is_archived=True и дата увольнения наступила или прошла"""
        if not self.is_archived:
            return False
        if self.archived_at is None:
            return True
        return self.archived_at <= datetime.date.today()

    @property
    def is_admin(self):
        return self.role in ['admin', 'curator']

    @property
    def is_curator(self):
        return self.role == 'curator'

    def __repr__(self):
        return f'<User {self.username}>'
