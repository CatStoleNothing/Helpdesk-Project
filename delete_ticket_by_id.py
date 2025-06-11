import sys
from models.db_init import SessionLocal
from models.ticket_models import Ticket, Message, Attachment

def delete_ticket(ticket_id):
    db = SessionLocal()
    try:
        ticket = db.get(Ticket, ticket_id)
        if not ticket:
            print(f'Заявка с ID {ticket_id} не найдена.')
            return
        # Удаляем связанные сообщения и вложения
        for message in ticket.messages:
            for attachment in message.attachments:
                db.delete(attachment)
            db.delete(message)
        for attachment in ticket.attachments:
            db.delete(attachment)
        db.delete(ticket)
        db.commit()
        print(f'Заявка с ID {ticket_id} и все связанные данные удалены.')
    except Exception as e:
        db.rollback()
        print(f'Ошибка при удалении: {e}')
    finally:
        db.close()

if __name__ == "__main__":
    ticket_id = input("Введите ID заявки для удаления: ").strip()
    if not ticket_id.isdigit():
        print("ID должен быть числом!")
        sys.exit(1)
    delete_ticket(int(ticket_id)) 