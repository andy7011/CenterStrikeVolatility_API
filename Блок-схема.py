import matplotlib.pyplot as plt
import numpy as np
from matplotlib.patches import FancyBboxPatch, Circle

# Создание графика с увеличенным размером
fig, ax = plt.subplots(figsize=(25, 18))


# Определение типов блоков
class BlockType:
    START_STOP = "start_stop"
    PROCESS = "process"
    DECISION = "decision"
    INPUT_OUTPUT = "input_output"
    SUBROUTINE = "subroutine"


# Цвета для разных категорий
colors = {
    BlockType.START_STOP: "#4CAF50",  # Зеленый для начала/конца
    BlockType.PROCESS: "#2196F3",  # Синий для процессов
    BlockType.DECISION: "#FF9800",  # Оранжевый для решений
    BlockType.INPUT_OUTPUT: "#9C27B0",  # Фиолетовый для ввода/вывода
    BlockType.SUBROUTINE: "#FF5722"  # Красный для подпрограмм
}


# Формы блоков
def draw_block(ax, x, y, text, block_type, width=1.2, height=0.8, **kwargs):
    """Рисование блока с учетом типа"""
    if block_type == BlockType.START_STOP:
        # Овал для начала/конца - ИСПРАВЛЕНО: только центр и радиус
        ellipse = plt.Circle((x, y), width / 2,
                             facecolor=colors[block_type],
                             edgecolor='black',
                             linewidth=1.5)
        ax.add_patch(ellipse)
        plt.text(x, y, text, ha='center', va='center',
                 fontsize=9, fontweight='bold', color='white')

    elif block_type == BlockType.DECISION:
        # Ромб для принятия решений
        diamond = plt.Polygon([(x - width / 2, y), (x, y + height / 2), (x + width / 2, y), (x, y - height / 2)],
                              facecolor=colors[block_type],
                              edgecolor='black',
                              linewidth=1.5)
        ax.add_patch(diamond)
        plt.text(x, y, text, ha='center', va='center',
                 fontsize=9, fontweight='bold', color='white')

    elif block_type == BlockType.INPUT_OUTPUT:
        # Параллелограмм для ввода/вывода
        parallelogram = plt.Polygon([(x - width / 2, y - height / 2), (x - width / 2 + 0.3, y - height / 2),
                                     (x + width / 2, y + height / 2), (x + width / 2 - 0.3, y + height / 2)],
                                    facecolor=colors[block_type],
                                    edgecolor='black',
                                    linewidth=1.5)
        ax.add_patch(parallelogram)
        plt.text(x, y, text, ha='center', va='center',
                 fontsize=9, fontweight='bold', color='white')

    else:
        # Прямоугольник для стандартных процессов
        rect = plt.Rectangle((x - width / 2, y - height / 2), width, height,
                             facecolor=colors[block_type],
                             edgecolor='black',
                             linewidth=1.5)
        ax.add_patch(rect)
        plt.text(x, y, text, ha='center', va='center',
                 fontsize=9, fontweight='bold', color='white')


# Основные блоки программы с увеличенными интервалами
main_blocks = {
    "Начало": (0, 12),
    "Инициализация": (0, 10),
    "Подключение к API": (0, 8),
    "Создание GUI": (0, 6),
    "Выбор базового актива": (0, 4),
    "Подписка на котировки": (0, 2),
    "Обработка событий": (2, 2),
    "Получение позиций": (4, 2),
    "Обработка котировок": (6, 2),
    "Обработка заявок": (8, 2),
    "Обработка сделок": (10, 2),
    "Завершение": (12, 2)
}

# Типы блоков для основных элементов
main_block_types = {
    "Начало": BlockType.START_STOP,
    "Инициализация": BlockType.PROCESS,
    "Подключение к API": BlockType.PROCESS,
    "Создание GUI": BlockType.PROCESS,
    "Выбор базового актива": BlockType.PROCESS,
    "Подписка на котировки": BlockType.PROCESS,
    "Обработка событий": BlockType.SUBROUTINE,
    "Получение позиций": BlockType.SUBROUTINE,
    "Обработка котировок": BlockType.SUBROUTINE,
    "Обработка заявок": BlockType.SUBROUTINE,
    "Обработка сделок": BlockType.SUBROUTINE,
    "Завершение": BlockType.START_STOP
}

# Рисование основных блоков
for block, (x, y) in main_blocks.items():
    draw_block(ax, x, y, block, main_block_types[block])

# Рисование стрелок между основными блоками с учетом границ блоков
for i in range(len(list(main_blocks.keys())) - 1):
    x1, y1 = main_blocks[list(main_blocks.keys())[i]]
    x2, y2 = main_blocks[list(main_blocks.keys())[i + 1]]

    # Рассчитываем точку на границе первого блока
    # Для вертикальных стрелок - просто до границы блока
    if x1 == x2:  # Вертикальная стрелка
        # Нижняя граница первого блока
        y1_end = y1 - 0.4  # 0.4 - половина высоты блока
        # Верхняя граница второго блока
        y2_start = y2 + 0.4  # 0.4 - половина высоты блока
        ax.annotate('', xy=(x2, y2_start), xytext=(x1, y1_end),
                    arrowprops=dict(arrowstyle='->', color='black', lw=2))
    else:  # Горизонтальная стрелка
        # Правая граница первого блока
        x1_end = x1 + 0.6  # 0.6 - половина ширины блока
        # Левая граница второго блока
        x2_start = x2 - 0.6  # 0.6 - половина ширины блока
        ax.annotate('', xy=(x2_start, y2), xytext=(x1_end, y1),
                    arrowprops=dict(arrowstyle='->', color='black', lw=2))

# Детализация "Обработка событий"
event_blocks = {
    "on_base_asset_change": (2, 0),
    "on_new_quotes": (2, -1.5),
    "on_order": (2, -3),
    "on_trade": (2, -4.5)
}

event_types = {
    "on_base_asset_change": BlockType.PROCESS,
    "on_new_quotes": BlockType.PROCESS,
    "on_order": BlockType.PROCESS,
    "on_trade": BlockType.PROCESS
}

for block, (x, y) in event_blocks.items():
    draw_block(ax, x, y, block, event_types[block])

# Стрелки от основного блока к событиям с учетом границ блоков
for i, (block, pos) in enumerate(event_blocks.items()):
    x1, y1 = main_blocks["Обработка событий"]
    x2, y2 = pos

    # Стрелка от правой границы блока "Обработка событий" к левой границе подблока
    x1_end = x1 + 0.6  # Правая граница
    x2_start = x2 - 0.6  # Левая граница подблока

    ax.annotate('', xy=(x2_start, y2), xytext=(x1_end, y1),
                arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))

# Детализация "Обработка котировок"
quote_blocks = {
    "Проверка новых котировок": (6, 0),
    "Проверка позиций": (6, -1.5),
    "Расчет целевой цены": (6, -3),
    "Создание заявки": (6, -4.5),
    "Отправка заявки": (6, -6),
    "Обновление order_dict": (6, -7.5),
    "Проверка исполнения": (6, -9)
}

quote_types = {
    "Проверка новых котировок": BlockType.PROCESS,
    "Проверка позиций": BlockType.PROCESS,
    "Расчет целевой цены": BlockType.PROCESS,
    "Создание заявки": BlockType.PROCESS,
    "Отправка заявки": BlockType.PROCESS,
    "Обновление order_dict": BlockType.PROCESS,
    "Проверка исполнения": BlockType.DECISION
}

for block, (x, y) in quote_blocks.items():
    draw_block(ax, x, y, block, quote_types[block])

# Стрелки между подблоками котировок с учетом границ блоков
for i in range(len(list(quote_blocks.keys())) - 1):
    x1, y1 = quote_blocks[list(quote_blocks.keys())[i]]
    x2, y2 = quote_blocks[list(quote_blocks.keys())[i + 1]]

    # Вертикальные стрелки - от нижней границы к верхней
    y1_end = y1 - 0.4  # Нижняя граница первого блока
    y2_start = y2 + 0.4  # Верхняя граница второго блока

    ax.annotate('', xy=(x2, y2_start), xytext=(x1, y1_end),
                arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))

# Детализация "Обработка заявок"
order_blocks = {
    "Проверка исполнения": (8, 0),
    "Проверка таймаута": (8, -1.5),
    "Отмена заявки": (8, -3),
    "Сброс контрольных значений": (8, -4.5),
    "Обновление портфеля": (8, -6)
}

order_types = {
    "Проверка исполнения": BlockType.DECISION,
    "Проверка таймаута": BlockType.DECISION,
    "Отмена заявки": BlockType.PROCESS,
    "Сброс контрольных значений": BlockType.PROCESS,
    "Обновление портфеля": BlockType.PROCESS
}

for block, (x, y) in order_blocks.items():
    draw_block(ax, x, y, block, order_types[block])

# Стрелки между подблоками заявок с учетом границ блоков
for i in range(len(list(order_blocks.keys())) - 1):
    x1, y1 = order_blocks[list(order_blocks.keys())[i]]
    x2, y2 = order_blocks[list(order_blocks.keys())[i + 1]]

    # Вертикальные стрелки - от нижней границы к верхней
    y1_end = y1 - 0.4  # Нижняя граница первого блока
    y2_start = y2 + 0.4  # Верхняя граница второго блока

    ax.annotate('', xy=(x2, y2_start), xytext=(x1, y1_end),
                arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))

# Детализация "Получение позиций"
position_blocks = {
    "get_portfolio_positions": (4, 0),
    "Проверка позиций": (4, -1.5),
    "Обновление данных": (4, -3)
}

position_types = {
    "get_portfolio_positions": BlockType.PROCESS,
    "Проверка позиций": BlockType.DECISION,
    "Обновление данных": BlockType.PROCESS
}

for block, (x, y) in position_blocks.items():
    draw_block(ax, x, y, block, position_types[block])

# Стрелки между подблоками позиций с учетом границ блоков
for i in range(len(list(position_blocks.keys())) - 1):
    x1, y1 = position_blocks[list(position_blocks.keys())[i]]
    x2, y2 = position_blocks[list(position_blocks.keys())[i + 1]]

    # Вертикальные стрелки - от нижней границы к верхней
    y1_end = y1 - 0.4  # Нижняя граница первого блока
    y2_start = y2 + 0.4  # Верхняя граница второго блока

    ax.annotate('', xy=(x2, y2_start), xytext=(x1, y1_end),
                arrowprops=dict(arrowstyle='->', color='gray', lw=1.5))

# Добавление поясняющих линий с учетом границ блоков
# Линия от основного блока к подблокам
ax.annotate('', xy=(2.4, 0), xytext=(2.4, 2.1),
            arrowprops=dict(arrowstyle='->', color='black', lw=1.5))

ax.annotate('', xy=(4.4, 0), xytext=(4.4, 2.1),
            arrowprops=dict(arrowstyle='->', color='black', lw=1.5))

ax.annotate('', xy=(6.4, 0), xytext=(6.4, 2.1),
            arrowprops=dict(arrowstyle='->', color='black', lw=1.5))

ax.annotate('', xy=(8.4, 0), xytext=(8.4, 2.1),
            arrowprops=dict(arrowstyle='->', color='black', lw=1.5))


# Добавление иконок (простые символы)
def add_icon(ax, x, y, icon_char, size=0.3):
    """Добавление иконки в блок"""
    ax.text(x, y, icon_char, ha='center', va='center',
            fontsize=size * 25, fontweight='bold', color='white')


# Добавление иконок к ключевым блокам
add_icon(ax, 0, 12, "▶", 0.25)  # Иконка начала
add_icon(ax, 0, 2, "⚙", 0.25)  # Иконка настройки
add_icon(ax, 6, 2, "📈", 0.25)  # Иконка котировок
add_icon(ax, 8, 2, "📝", 0.25)  # Иконка заявок
add_icon(ax, 12, 2, "⏹", 0.25)  # Иконка завершения

# Добавление легенды
legend_elements = [
    plt.Rectangle((0, 0), 1, 1, facecolor=colors[BlockType.START_STOP], label="Начало/Конец"),
    plt.Rectangle((0, 0), 1, 1, facecolor=colors[BlockType.PROCESS], label="Процесс"),
    plt.Rectangle((0, 0), 1, 1, facecolor=colors[BlockType.DECISION], label="Принятие решений"),
    plt.Rectangle((0, 0), 1, 1, facecolor=colors[BlockType.INPUT_OUTPUT], label="Ввод/Вывод"),
    plt.Rectangle((0, 0), 1, 1, facecolor=colors[BlockType.SUBROUTINE], label="Подпрограмма")
]

ax.legend(handles=legend_elements, loc='upper left', bbox_to_anchor=(0.02, 0.98),
          title="Категории блоков", fontsize=10, title_fontsize=12)

# Установка границ и удаление осей
plt.xlim(-1, 13)
plt.ylim(-10, 14)
plt.axis('off')
plt.title("Блок-схема работы программы 02MyCloser.py\nДетализация с улучшениями", fontsize=18, pad=20)

# Сохранение в файл
plt.tight_layout()
plt.savefig('block_schema_enhanced_fixed.png', dpi=300, bbox_inches='tight')
plt.show()
