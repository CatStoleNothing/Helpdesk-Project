"""migrate assigned_to to assignee_id

Revision ID: migrate_assigned_to_to_assignee_id
Revises: 
Create Date: 2024-03-19

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.orm import Session
from models.user_models import User

# revision identifiers, used by Alembic.
revision = 'migrate_assigned_to_to_assignee_id'
down_revision = None
branch_labels = None
depends_on = None

def upgrade():
    # Создаем временную колонку assignee_id если её нет
    op.add_column('tickets', sa.Column('assignee_id', sa.Integer(), nullable=True))
    
    # Получаем соединение с базой данных
    connection = op.get_bind()
    session = Session(bind=connection)
    
    # Получаем все заявки с заполненным assigned_to
    tickets = connection.execute(
        "SELECT id, assigned_to FROM tickets WHERE assigned_to IS NOT NULL AND assigned_to != ''"
    ).fetchall()
    
    # Для каждой заявки находим пользователя по chat_id и обновляем assignee_id
    for ticket in tickets:
        user = session.query(User).filter(User.chat_id == ticket.assigned_to).first()
        if user:
            connection.execute(
                "UPDATE tickets SET assignee_id = %s WHERE id = %s",
                (user.id, ticket.id)
            )
    
    # Создаем внешний ключ
    op.create_foreign_key(
        'fk_tickets_assignee_id_users',
        'tickets', 'users',
        ['assignee_id'], ['id']
    )

def downgrade():
    # Удаляем внешний ключ
    op.drop_constraint('fk_tickets_assignee_id_users', 'tickets', type_='foreignkey')
    
    # Удаляем колонку assignee_id
    op.drop_column('tickets', 'assignee_id') 