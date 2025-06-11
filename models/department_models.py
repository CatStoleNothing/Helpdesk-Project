from sqlalchemy import Column, Integer, String, Date, Boolean, ForeignKey
from sqlalchemy.orm import relationship, validates
from datetime import datetime
from models.db_init import Base

class Department(Base):
    __tablename__ = "departments"

    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    active_from = Column(Date, nullable=True)
    active_to = Column(Date, nullable=True)
    is_active = Column(Boolean, default=True)

    # Связи
    users = relationship("User", back_populates="department")
    offices = relationship("Office", back_populates="department")

    @property
    def is_currently_active(self):
        """Проверяет, активен ли отдел в текущий момент"""
        now = datetime.now().date()
        if self.active_from and self.active_to:
            return self.active_from <= now <= self.active_to
        elif self.active_from:
            return self.active_from <= now
        elif self.active_to:
            return now <= self.active_to
        return True

    def update_active_status(self):
        """Обновляет статус активности отдела"""
        self.is_active = self.is_currently_active

    @validates('active_from', 'active_to')
    def validate_dates(self, key, value):
        """Валидация дат и обновление статуса активности"""
        if value and key == 'active_to' and self.active_from and value < self.active_from:
            raise ValueError("Дата окончания активности не может быть раньше даты начала")
        self.update_active_status()
        return value 