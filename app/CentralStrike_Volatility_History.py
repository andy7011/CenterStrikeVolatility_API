import schedule
import time
from typing import NoReturn

def job() -> NoReturn:
    """
    Пример задачи, которая выполняет печать текущего времени.
    """
    print("Запуск задачи в", time.strftime('%Y-%m-%d %H:%M:%S'))

# Запускаем задачу каждую минуту
schedule.every(1).minutes.do(job)

def run_scheduler() -> NoReturn:
    """
    Функция для запуска планировщика.
    """
    while True:
        schedule.run_pending()
        time.sleep(1)

if __name__ == "__main__":
    run_scheduler()