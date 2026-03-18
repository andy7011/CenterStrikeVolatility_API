# main.py
import threading
import signal
import MyControlPanel
import MyQuoteRobot_v1_6

def signal_handler(sig, frame):
    print('Программа завершается...')
    # Здесь можно добавить дополнительную логику завершения
    exit(0)

# Регистрируем обработчик сигнала в основном потоке
signal.signal(signal.SIGINT, signal_handler)
signal.signal(signal.SIGTERM, signal_handler)

# Запуск интерфейса в основном потоке
def run_gui():
    MyControlPanel.root.mainloop()

# Запуск робота в отдельном потоке
robot_thread = threading.Thread(target=MyQuoteRobot_v1_6.main)
robot_thread.daemon = True
robot_thread.start()

# Запуск GUI в основном потоке
run_gui()
