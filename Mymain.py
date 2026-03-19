# Mymain.py
import threading
import MyControlPanel
import MyQuoteRobot_v1_6

if __name__ == "__main__":
    # Запуск GUI в основном потоке
    gui_thread = threading.Thread(target=MyQuoteRobot_v1_6.run_gui)
    gui_thread.daemon = True
    gui_thread.start()

    # Запуск основного цикла в отдельном потоке
    main_thread = threading.Thread(target=MyQuoteRobot_v1_6.main_loop)
    main_thread.daemon = True
    main_thread.start()

    # Ожидание завершения
    gui_thread.join()
