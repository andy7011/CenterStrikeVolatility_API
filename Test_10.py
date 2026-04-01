import tkinter as tk
from tkinter import ttk

def set_dark_theme():
    style = ttk.Style()
    style.theme_use('clam')  # Используем тему 'clam' как основу

    # Определяем цвета
    bg = '#2e2e2e'
    fg = '#ffffff'
    select_bg = '#4a4a4a'
    field_bg = '#3c3c3c'
    disabled_fg = '#777777'

    # Применяем стили
    style.configure('.', background=bg, foreground=fg)
    style.configure('TFrame', background=bg)
    style.configure('TLabel', background=bg, foreground=fg)
    style.configure('TButton', background=field_bg, foreground=fg)
    style.configure('TEntry', fieldbackground=field_bg, foreground=fg)
    style.configure('TCombobox', fieldbackground=field_bg, foreground=fg)
    style.map('TCombobox', fieldbackground=[('readonly', field_bg)])
    style.configure('TCheckbutton', background=bg, foreground=fg)
    style.configure('TRadiobutton', background=bg, foreground=fg)
    style.configure('Treeview', background=field_bg, foreground=fg)
    style.configure('Vertical.TScrollbar', background=bg)
    style.configure('Horizontal.TScrollbar', background=bg)

root = tk.Tk()
set_dark_theme()

# Пример элементов
ttk.Label(root, text="Темная тема").pack(pady=10)
ttk.Entry(root).pack(pady=5)
ttk.Button(root, text="Кнопка").pack(pady=5)

root.mainloop()
