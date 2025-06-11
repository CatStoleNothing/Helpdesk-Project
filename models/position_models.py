from sqlalchemy import Column, Integer, String, Date, Boolean
from sqlalchemy.orm import relationship, validates
from datetime import datetime
from models.db_init import Base

class Position(Base):
    __tablename__ = "positions"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    active_from = Column(Date, nullable=True)
    active_to = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)

    users = relationship("User", back_populates="position")

    @property
    def is_currently_active(self):
        """Проверяет, активна ли должность в текущий момент"""
        now = datetime.now().date()
        if self.active_from and self.active_to:
            return self.active_from <= now <= self.active_to
        elif self.active_from:
            return self.active_from <= now
        elif self.active_to:
            return now <= self.active_to
        return True

    def update_active_status(self):
        """Обновляет статус активности должности"""
        self.is_active = self.is_currently_active

    @validates('active_from', 'active_to')
    def validate_dates(self, key, value):
        """Валидация дат и обновление статуса активности"""
        if value and key == 'active_to' and self.active_from and value < self.active_from:
            raise ValueError("Дата окончания активности не может быть раньше даты начала")
        self.update_active_status()
        return value 