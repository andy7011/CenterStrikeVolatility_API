import tkinter as tk
from tkinter import ttk
import time


class App:
    def __init__(self):
        self.root = tk.Tk()
        self.root.title("Non-blocking loop example")
        self.root.geometry("400x300")

        self.running = False
        self.counter = 0

        # Создаем кнопки
        self.start_button = tk.Button(self.root, text="Start", command=self.start_loop)
        self.start_button.pack(pady=10)

        self.stop_button = tk.Button(self.root, text="Stop", command=self.stop_loop)
        self.stop_button.pack(pady=10)

        self.status_label = tk.Label(self.root, text="Status: Stopped")
        self.status_label.pack(pady=10)

        self.counter_label = tk.Label(self.root, text="Counter: 0")
        self.counter_label.pack(pady=10)

    def loop_function(self):
        """Функция, которая будет выполняться в цикле"""
        if self.running:
            self.counter += 1
            self.counter_label.config(text=f"Counter: {self.counter}")
            self.status_label.config(text="Status: Running")

            # Планируем следующий вызов через 100 мс
            self.root.after(1000, self.loop_function)

    def start_loop(self):
        """Запуск цикла"""
        if not self.running:
            self.running = True
            self.loop_function()  # Запускаем цикл

    def stop_loop(self):
        """Остановка цикла"""
        self.running = False
        self.status_label.config(text="Status: Stopped")


# Запуск приложения
if __name__ == "__main__":
    app = App()
    app.root.mainloop()
