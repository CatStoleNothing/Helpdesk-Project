// JavaScript для страницы ticket_detail.html

$(document).ready(function() {
    // Обработка изменений в редактируемых полях
    $('.editable-field').on('change', function() {
        const field = $(this).data('field');
        const ticketId = $(this).data('ticket-id');
        const value = $(this).val();

        if (field === 'category') {
            // Смена категории через отдельный эндпоинт
            $.ajax({
                url: `/ticket/${ticketId}/change_category`,
                method: 'POST',
                contentType: 'application/x-www-form-urlencoded',
                data: `category_id=${value}`,
                success: function(response) {
                    if (response.success) {
                        showNotification('success', 'Категория успешно изменена');
                        setTimeout(() => { location.reload(); }, 1000);
                    } else {
                        showNotification('error', response.error || 'Ошибка при изменении категории');
                    }
                },
                error: function(xhr) {
                    showNotification('error', 'Ошибка при изменении категории');
                }
            });
            return;
        }

        // Отправляем AJAX запрос для обновления поля
        $.ajax({
            url: `/api/ticket/${ticketId}/update`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                field: field,
                value: value
            }),
            success: function(response) {
                if (response.success) {
                    // Показываем уведомление об успехе
                    showNotification('success', response.message);
                    // Перезагружаем страницу для обновления интерфейса
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                } else {
                    showNotification('error', response.message);
                }
            },
            error: function(xhr) {
                const response = xhr.responseJSON || {};
                showNotification('error', response.message || 'Произошла ошибка');
            }
        });
    });

    // Обработка кнопки "Завершить"
    $('#resolveTicket').on('click', function() {
        const ticketId = $(this).data('ticket-id');
        showStatusChangeModal('resolved', 'завершить', ticketId);
    });

    // Обработка кнопки "Неактуально"
    $('#markAsIrrelevant').on('click', function() {
        const ticketId = $(this).data('ticket-id');
        showStatusChangeModal('irrelevant', 'отметить как неактуальную', ticketId);
    });

    // Обработка кнопки "Вернуть в работу"
    $('#returnToWork').on('click', function() {
        const ticketId = $(this).data('ticket-id');
        showStatusChangeModal('in_progress', 'вернуть в работу', ticketId);
    });

    // Показать модальное окно изменения статуса
    function showStatusChangeModal(status, actionText, ticketId) {
        $('#statusActionText').text(actionText);
        $('#newStatus').val(status);
        $('#statusChangeForm').data('ticket-id', ticketId);
        $('#statusChangeModal').modal('show');
    }

    // Подтверждение изменения статуса
    $('#confirmStatusChange').on('click', function() {
        const ticketId = $('#statusChangeForm').data('ticket-id');
        const status = $('#newStatus').val();
        const reason = $('#statusChangeReason').val();

        $.ajax({
            url: `/api/ticket/${ticketId}/status`,
            method: 'POST',
            contentType: 'application/json',
            data: JSON.stringify({
                status: status,
                reason: reason
            }),
            success: function(response) {
                if (response.success) {
                    $('#statusChangeModal').modal('hide');
                    showNotification('success', response.message);
                    // Перезагружаем страницу для обновления интерфейса
                    setTimeout(() => {
                        location.reload();
                    }, 1000);
                } else {
                    showNotification('error', response.message);
                }
            },
            error: function(xhr) {
                const response = xhr.responseJSON || {};
                showNotification('error', response.message || 'Произошла ошибка');
            }
        });
    });

    // Функция для показа уведомлений
    function showNotification(type, message) {
        const alertClass = type === 'success' ? 'alert-success' : 'alert-danger';
        const notification = `
            <div class="alert ${alertClass} alert-dismissible fade show position-fixed"
                 style="top: 20px; right: 20px; z-index: 9999; min-width: 300px;">
                ${message}
                <button type="button" class="btn-close" data-bs-dismiss="alert"></button>
            </div>
        `;
        $('body').append(notification);

        // Автоматически скрыть через 5 секунд
        setTimeout(() => {
            $('.alert').fadeOut();
        }, 5000);
    }

    // Очистка формы при закрытии модального окна
    $('#statusChangeModal').on('hidden.bs.modal', function() {
        $('#statusChangeReason').val('');
    });

    function getStatusName(statusId) {
        if (window.STATUSES) {
            const found = window.STATUSES.find(s => s.id === statusId);
            return found ? found.name : statusId;
        }
        return statusId;
    }

    // Обработчик изменения статуса заявки
});