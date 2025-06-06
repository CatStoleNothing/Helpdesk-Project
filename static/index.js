document.addEventListener("DOMContentLoaded", function () {
    // Найдем форму и контейнер таблицы (важно: tbody или div.card-body!)
    const ticketsFiltersForm = document.querySelector(".filters-form");
    const ticketsTableContainer = document.querySelector(".card > .card-body"); // предполагаем, что таблица одна на странице

    if (ticketsFiltersForm && ticketsTableContainer) {
        // Выделим все элементы с классом .form-control внутри фильтров
        const filterInputs = ticketsFiltersForm.querySelectorAll(".form-control, select");

        // Лоадер поверх таблицы
        function showLoader() {
            let loader = document.getElementById("table-loader");
            if (!loader) {
                loader = document.createElement("div");
                loader.id = "table-loader";
                loader.style.background = "rgba(255,255,255,0.7) url('https://same-assets.com/spinner.svg') center center no-repeat";
                loader.style.position = "absolute";
                loader.style.inset = "0";
                loader.style.zIndex = "10";
                loader.innerHTML = "";
                ticketsTableContainer.style.position = "relative";
                ticketsTableContainer.appendChild(loader);
            }
            loader.style.display = "block";
        }
        function hideLoader() {
            const loader = document.getElementById("table-loader");
            if (loader) loader.style.display = "none";
        }

        // Отправка запроса
        function submitFilters(page = 1) {
            const formData = new FormData(ticketsFiltersForm);
            formData.set('page', page);
            showLoader();
            fetch("/tickets/fragment", {
                method: "POST",
                headers: {
                    'X-Requested-With': 'XMLHttpRequest'
                },
                body: formData
            })
                .then(resp => resp.text())
                .then(html => {
                    ticketsTableContainer.innerHTML = html;
                    // После загрузки новой таблицы, применяем к ней сортировку
                    initSortableTables();
                })
                .catch(() => {
                    ticketsTableContainer.innerHTML = '<div class="alert alert-danger">Ошибка загрузки.</div>';
                })
                .finally(hideLoader);
        }

        // При любом изменении фильтра
        filterInputs.forEach(input => {
            input.addEventListener("change", () => submitFilters());
        });

        // Перехватим submit формы (если жмут Enter или кнопку)
        ticketsFiltersForm.addEventListener("submit", function (e) {
            e.preventDefault();
            submitFilters();
        });

        // Делегируем клик по пагинации (перезапрос с другими параметрами)
        ticketsTableContainer.addEventListener("click", function (e) {
            const target = e.target.closest("a[data-page]");
            if (target) {
                e.preventDefault();
                const page = target.getAttribute('data-page');
                submitFilters(page);
            }
        });
    }

    // === Сортировка таблиц ===
    function initSortableTables() {
        const tables = document.querySelectorAll('table.sortable, table.table-striped');
        tables.forEach(table => {
            const tableId = table.id || 'table_' + Math.floor(Math.random() * 10000);
            if (!table.id) table.id = tableId;

            // Добавляем класс sortable к таблице, если его нет
            if (!table.classList.contains('sortable')) {
                table.classList.add('sortable');
            }

            // Получаем сохраненные настройки сортировки для текущей таблицы
            const savedSortSettings = getSavedSortSettings(tableId);

            const headers = table.querySelectorAll('th');
            headers.forEach((header, index) => {
                // Пропускаем столбцы с действиями (без текста или с кнопками)
                if (header.innerText.trim() === '' || header.classList.contains('no-sort')) {
                    return;
                }

                // Добавляем классы и обработчики для сортировки, если ещё не добавлены
                if (!header.classList.contains('sortable')) {
                    header.classList.add('sortable');
                }

                // Проверяем, есть ли уже индикатор сортировки
                let sortIndicator = header.querySelector('.sort-indicator');

                if (!sortIndicator) {
                    // Добавляем индикатор сортировки
                    sortIndicator = document.createElement('span');
                    sortIndicator.className = 'sort-indicator';
                    sortIndicator.innerHTML = '&nbsp;';
                    header.appendChild(sortIndicator);
                }

                // Если есть сохраненные настройки для этого столбца
                if (savedSortSettings && savedSortSettings.columnIndex === index) {
                    header.classList.add(savedSortSettings.direction === 'asc' ? 'sort-asc' : 'sort-desc');
                    // Сортируем таблицу при инициализации согласно сохраненным настройкам
                    sortTable(table, index, savedSortSettings.direction === 'asc');
                }

                // Очищаем обработчики перед добавлением нового (чтобы избежать дублирования)
                header.removeEventListener('click', headerClickHandler);

                // Устанавливаем обработчик для сортировки
                header.addEventListener('click', headerClickHandler);
            });
        });
    }

    // Выносим функцию обработки клика в отдельную именованную функцию
    function headerClickHandler() {
        const header = this;
        const table = header.closest('table');
        const headers = table.querySelectorAll('th');
        const tableId = table.id;

        // Находим индекс текущего заголовка
        let columnIndex = 0;
        for (let i = 0; i < headers.length; i++) {
            if (headers[i] === header) {
                columnIndex = i;
                break;
            }
        }

        // Определяем направление сортировки
        const isAscending = !header.classList.contains('sort-asc');

        // Убираем предыдущие индикаторы сортировки
        headers.forEach(h => {
            h.classList.remove('sort-asc', 'sort-desc');
        });

        // Добавляем текущий индикатор
        header.classList.add(isAscending ? 'sort-asc' : 'sort-desc');

        // Сортируем таблицу
        sortTable(table, columnIndex, isAscending);

        // Сохраняем настройки сортировки
        saveTableSortSettings(tableId, columnIndex, isAscending ? 'asc' : 'desc');
    }

    // Функция сортировки таблицы
    function sortTable(table, columnIndex, ascending) {
        const tbody = table.querySelector('tbody');
        const rows = Array.from(tbody.querySelectorAll('tr'));

        // Сортируем строки
        rows.sort((rowA, rowB) => {
            // Проверяем наличие ячеек нужного индекса
            if (!rowA.cells[columnIndex] || !rowB.cells[columnIndex]) {
                return 0;
            }

            let cellA = rowA.cells[columnIndex].innerText.trim();
            let cellB = rowB.cells[columnIndex].innerText.trim();

            // Проверка и обработка дат в формате дд.мм.гггг чч:мм
            const dateRegex = /^\d{2}\.\d{2}\.\d{4}\s\d{2}:\d{2}$/;
            if (dateRegex.test(cellA) && dateRegex.test(cellB)) {
                // Преобразование дат в формате dd.mm.yyyy hh:mm в объекты Date
                const partsA = cellA.split(' ');
                const datePartsA = partsA[0].split('.');
                const timePartsA = partsA[1].split(':');
                const dateA = new Date(
                    datePartsA[2], datePartsA[1] - 1, datePartsA[0],
                    timePartsA[0], timePartsA[1]
                );

                const partsB = cellB.split(' ');
                const datePartsB = partsB[0].split('.');
                const timePartsB = partsB[1].split(':');
                const dateB = new Date(
                    datePartsB[2], datePartsB[1] - 1, datePartsB[0],
                    timePartsB[0], timePartsB[1]
                );

                return ascending ? dateA - dateB : dateB - dateA;
            }

            // Проверяем, является ли значение числом
            const isNumericA = !isNaN(parseFloat(cellA));
            const isNumericB = !isNaN(parseFloat(cellB));

            // Если оба значения числовые, сортируем как числа
            if (isNumericA && isNumericB) {
                return ascending
                    ? parseFloat(cellA) - parseFloat(cellB)
                    : parseFloat(cellB) - parseFloat(cellA);
            }

            // Иначе сортируем как строки
            return ascending
                ? cellA.localeCompare(cellB, 'ru')
                : cellB.localeCompare(cellA, 'ru');
        });

        // Обновляем DOM
        rows.forEach(row => tbody.appendChild(row));
    }

    // Функция для сохранения настроек сортировки
    function saveTableSortSettings(tableId, columnIndex, direction) {
        if (!window.localStorage) return;

        try {
            const userSettings = JSON.parse(localStorage.getItem('userTableSettings') || '{}');
            userSettings[tableId] = { columnIndex, direction };
            localStorage.setItem('userTableSettings', JSON.stringify(userSettings));
        } catch (e) {
            console.error('Ошибка сохранения настроек сортировки:', e);
        }
    }

    // Функция для получения сохраненных настроек сортировки
    function getSavedSortSettings(tableId) {
        if (!window.localStorage) return null;

        try {
            const userSettings = JSON.parse(localStorage.getItem('userTableSettings') || '{}');
            return userSettings[tableId] || null;
        } catch (e) {
            console.error('Ошибка загрузки настроек сортировки:', e);
            return null;
        }
    }

    // Инициализируем сортировку таблиц при загрузке страницы
    initSortableTables();
});
