/**
 * Модуль для работы с чатами и файлами в заявках
 */
const TicketChat = (function() {
    /**
     * Инициализация всех функций чата
     */
    function init() {
        // Инициализация чатов
        initChats();

        // Инициализация обработчиков файлов
        initFileHandlers();

        // Инициализация просмотрщика изображений
        initImageViewer();

        // Инициализация изменения статуса заявки
        initStatusChange();
    }

    /**
     * Инициализация чатов
     */
    function initChats() {
        // Прокрутка чатов к последнему сообщению при загрузке
        scrollChatsToBottom();

        // Инициализация форм чата
        initChatForms();
    }

    /**
     * Прокрутка чатов к последнему сообщению
     */
    function scrollChatsToBottom() {
        const userChatMessages = document.getElementById('userChatMessages');
        const internalChatMessages = document.getElementById('internalChatMessages');

        if (userChatMessages) {
            userChatMessages.scrollTop = userChatMessages.scrollHeight;
        }

        if (internalChatMessages) {
            internalChatMessages.scrollTop = internalChatMessages.scrollHeight;
        }
    }

    /**
     * Инициализация обработчиков файлов
     */
    function initFileHandlers() {
        // Обработчики выбора файлов
        const fileInputs = document.querySelectorAll('input[type="file"]');
        fileInputs.forEach(input => {
            input.addEventListener('change', function() {
                const previewId = this.id === 'userFileInput' ? 'userFilePreview' : 'internalFilePreview';
                handleFileSelection(this, previewId);
            });
        });

        // Обработчики кнопок удаления файлов
        const removeButtons = document.querySelectorAll('.remove-file');
        removeButtons.forEach(button => {
            button.addEventListener('click', function() {
                const previewContainer = this.closest('.file-preview');
                const form = previewContainer.closest('form');
                const fileInput = form.querySelector('input[type="file"]');

                fileInput.value = '';
                previewContainer.classList.add('d-none');
            });
        });
    }

    /**
     * Инициализация форм чата
     */
    function initChatForms() {
        // Обработчик формы пользовательского чата
        const userChatForm = document.getElementById('userChatForm');
        if (userChatForm) {
            userChatForm.addEventListener('submit', function(e) {
                e.preventDefault();
                sendChatMessage(this, 'userChatMessages', 'userMessageInput', 'userFileInput', 'userFilePreview');
            });
        }

        // Обработчик формы внутреннего чата
        const internalChatForm = document.getElementById('internalChatForm');
        if (internalChatForm) {
            internalChatForm.addEventListener('submit', function(e) {
                e.preventDefault();
                sendChatMessage(this, 'internalChatMessages', 'internalMessageInput', 'internalFileInput', 'internalFilePreview');
            });
        }
    }

    /**
     * Обработка выбора файла
     * @param {HTMLInputElement} input - поле загрузки файла
     * @param {string} previewContainerId - ID контейнера предпросмотра
     */
    function handleFileSelection(input, previewContainerId) {
        const previewContainer = document.getElementById(previewContainerId);
        const fileNameElement = previewContainer.querySelector('.file-name');

        if (input.files && input.files.length > 0) {
            const file = input.files[0];
            fileNameElement.textContent = file.name;

            // Проверка на размер файла (максимум 10 МБ)
            if (file.size > 10 * 1024 * 1024) {
                alert('Файл слишком большой. Максимальный размер файла - 10 МБ.');
                input.value = '';
                previewContainer.classList.add('d-none');
                return;
            }

            previewContainer.classList.remove('d-none');
        } else {
            previewContainer.classList.add('d-none');
        }
    }

    /**
     * Отправка сообщения в чат
     * @param {HTMLFormElement} form - форма сообщения
     * @param {string} chatContainerId - ID контейнера сообщений
     * @param {string} messageInputId - ID поля ввода сообщения
     * @param {string} fileInputId - ID поля загрузки файла
     * @param {string} filePreviewId - ID контейнера предпросмотра файла
     */
    function sendChatMessage(form, chatContainerId, messageInputId, fileInputId, filePreviewId) {
        const formData = new FormData(form);
        const messageInput = document.getElementById(messageInputId);
        const fileInput = document.getElementById(fileInputId);
        const messageText = messageInput.value.trim();
        const hasFile = fileInput.files && fileInput.files.length > 0;

        // Проверяем, есть ли хотя бы сообщение или файл
        if (!messageText && !hasFile) {
            alert('Пожалуйста, введите сообщение или прикрепите файл');
            return;
        }

        // Если нет текста сообщения, но есть файл, устанавливаем пустое сообщение
        if (!messageText && hasFile) {
            formData.set('message', '');
        }

        fetch('/send_chat_message', {
            method: 'POST',
            body: formData
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                const chatMessages = document.getElementById(chatContainerId);
                const messageElement = document.createElement('div');
                messageElement.className = `chat-message ${data.message.is_internal ? 'outgoing' : 'incoming'}`;

                let sender = data.message.sender_name;
                if (data.message.sender_id == window.currentUserId) {
                    sender = "Вы";
                }
                let messageHTML = `
                    <div class="message-header">
                        <span class="message-sender">${sender}</span>
                        <span class="message-time">${data.message.created_at}</span>
                    </div>`;

                if (data.message.content) {
                    messageHTML += `<div class="message-content">${data.message.content}</div>`;
                }

                // Добавляем вложение, если есть
                if (data.message.attachment) {
                    messageHTML += `<div class="message-attachment">`;
                    if (data.message.attachment.is_image) {
                        messageHTML += `
                            <img src="${data.message.attachment.file_path}"
                                 alt="${data.message.attachment.file_name}"
                                 class="message-attachment-img image-viewer-trigger"
                                 data-image="${data.message.attachment.file_path}">`;
                    } else {
                        messageHTML += `
                            <div class="non-image-attachment">
                                <i class="fas fa-file me-2"></i>
                                <a href="${data.message.attachment.file_path}"
                                   download="${data.message.attachment.file_name}">
                                    ${data.message.attachment.file_name}
                                </a>
                            </div>`;
                    }
                    messageHTML += `</div>`;
                }

                messageElement.innerHTML = messageHTML;
                chatMessages.appendChild(messageElement);

                // Прокручиваем чат вниз
                chatMessages.scrollTop = chatMessages.scrollHeight;

                // Очищаем форму
                messageInput.value = '';
                fileInput.value = '';
                document.getElementById(filePreviewId).classList.add('d-none');
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось отправить сообщение'));
            }
        })
        .catch(error => {
            console.error('Ошибка при отправке сообщения:', error);
            alert('Произошла ошибка при отправке сообщения');
        });
    }

    /**
     * Инициализация просмотрщика изображений
     */
    function initImageViewer() {
        document.body.addEventListener('click', function(e) {
            if (e.target.classList.contains('image-viewer-trigger')) {
                e.preventDefault();

                const imageUrl = e.target.getAttribute('data-image') || e.target.src;
                const modalImage = document.getElementById('modalViewerImage');
                const downloadBtn = document.getElementById('downloadImageBtn');

                if (modalImage) {
                    modalImage.src = imageUrl;
                }

                // Настройка кнопки скачивания
                if (downloadBtn) {
                    downloadBtn.href = imageUrl;
                    let fileName = e.target.getAttribute('alt') || '';
                    if (!fileName || fileName.indexOf('.') === -1) {
                        try {
                            fileName = imageUrl.split('/').pop();
                        } catch (err) {
                            fileName = 'image.jpg';
                        }
                    }
                    downloadBtn.setAttribute('download', fileName);
                }

                // Показываем модальное окно
                const imageModal = document.getElementById('imageViewerModal');
                if (imageModal) {
                    const bsModal = new bootstrap.Modal(imageModal);
                    bsModal.show();
                }
            }
        });
    }

    /**
     * Инициализация обработчиков изменения статуса заявки
     */
    function initStatusChange() {
        const resolveBtn = document.getElementById('resolveTicket');
        if (resolveBtn) {
            resolveBtn.addEventListener('click', function() {
                showStatusChangeModal('resolved', 'завершить');
            });
        }

        const irrelevantBtn = document.getElementById('markAsIrrelevant');
        if (irrelevantBtn) {
            irrelevantBtn.addEventListener('click', function() {
                showStatusChangeModal('irrelevant', 'отметить как неактуальную');
            });
        }

        // Обработчик подтверждения изменения статуса
        const confirmBtn = document.getElementById('confirmStatusChange');
        if (confirmBtn) {
            confirmBtn.addEventListener('click', handleStatusChange);
        }
    }

    /**
     * Показать модальное окно смены статуса
     * @param {string} status - новый статус заявки
     * @param {string} actionText - текст действия для отображения
     */
    function showStatusChangeModal(status, actionText) {
        const newStatusInput = document.getElementById('newStatus');
        const statusActionText = document.getElementById('statusActionText');

        if (newStatusInput && statusActionText) {
            newStatusInput.value = status;
            statusActionText.textContent = actionText;

            const statusModal = document.getElementById('statusChangeModal');
            if (statusModal) {
                const bsModal = new bootstrap.Modal(statusModal);
                bsModal.show();
            }
        }
    }

    /**
     * Обработка изменения статуса заявки
     */
    function handleStatusChange() {
        const status = document.getElementById('newStatus').value;
        const reason = document.getElementById('statusChangeReason').value;
        const ticketId = document.querySelector('input[name="ticket_id"]').value;

        fetch(`/ticket/${ticketId}/change_status`, {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: `status=${status}&reason=${encodeURIComponent(reason)}`
        })
        .then(response => response.json())
        .then(data => {
            if (data.success) {
                // Обновляем статус на странице
                const statusElements = document.querySelectorAll('.badge.status-' + document.querySelector('.detail-value .badge').classList[1].split('-')[1]);
                statusElements.forEach(el => {
                    el.className = `badge status-${status}`;
                    el.textContent = status === 'resolved' ? 'Решена' : 'Неактуально';
                });

                // Добавляем системное сообщение в оба чата
                const systemMessage = `
                    <div class="chat-message">
                        <div class="message-header">
                            <span class="message-sender">Система</span>
                            <span class="message-time">${new Date().toLocaleString('ru')}</span>
                        </div>
                        <div class="message-content">
                            Статус заявки изменен на "${status === 'resolved' ? 'Решена' : 'Неактуально'}"
                            ${reason ? `<br>Причина: ${reason}` : ''}
                        </div>
                    </div>
                `;

                document.getElementById('userChatMessages').insertAdjacentHTML('beforeend', systemMessage);
                document.getElementById('internalChatMessages').insertAdjacentHTML('beforeend', systemMessage);

                // Прокручиваем чаты вниз
                scrollChatsToBottom();

                // Закрываем модальное окно
                const statusModal = document.getElementById('statusChangeModal');
                if (statusModal) {
                    bootstrap.Modal.getInstance(statusModal).hide();
                }

                // Показываем уведомление
                alert('Статус заявки успешно изменен');
            } else {
                alert('Ошибка: ' + (data.error || 'Не удалось изменить статус заявки'));
            }
        })
        .catch(error => {
            console.error('Ошибка при изменении статуса:', error);
            alert('Произошла ошибка при изменении статуса заявки');
        });
    }

    // Публичный API
    return {
        init: init,
        scrollChatsToBottom: scrollChatsToBottom
    };
})();

// Инициализация при загрузке DOM
document.addEventListener('DOMContentLoaded', function() {
    TicketChat.init();
});
