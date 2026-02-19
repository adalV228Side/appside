import customtkinter as ctk
import tkinter.messagebox as mb
import json
import os
import sys
import requests  # добавлен импорт
from equipment_ui import EquipmentWindow
from cartridges_ui import CartridgeWindow

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("dark-blue")

# --- Функции для обновления ---
VERSION_FILE = "version.txt"
BASE_RAW_URL = "https://raw.githubusercontent.com/adalV228Side/my-launcher/refs/heads/main/"
VERSION_URL = BASE_RAW_URL + "version.txt"
FILES_TO_UPDATE = ["Launcher.exe", "version.txt"]  # обновляемые файлы

def get_current_version():
    """Возвращает текущую версию из version.txt или '0.0.0'"""
    if os.path.exists(VERSION_FILE):
        with open(VERSION_FILE, "r", encoding="utf-8") as f:
            return f.read().strip()
    return "0.0.0"

CURRENT_VERSION = get_current_version()

def check_for_updates(silent=False):
    """
    Проверяет наличие обновлений.
    Если silent=False, показывает сообщение при отсутствии обновлений.
    Возвращает True, если обновление доступно и пользователь согласился установить.
    """
    try:
        response = requests.get(VERSION_URL, timeout=5)
        if response.status_code != 200:
            if not silent:
                mb.showerror("Ошибка", "Не удалось проверить обновления (сервер недоступен).")
            return False
        latest_version = response.text.strip()

        # Простое строковое сравнение (можно заменить на семантическое)
        if latest_version > CURRENT_VERSION:
            if mb.askyesno("Обновление",
                           f"Доступна новая версия {latest_version}.\n"
                           f"Текущая версия: {CURRENT_VERSION}\n\n"
                           "Установить сейчас? (приложение закроется)"):
                perform_update()
                return True
        else:
            if not silent:
                mb.showinfo("Обновления", "У вас актуальная версия.")
        return False
    except Exception as e:
        if not silent:
            mb.showerror("Ошибка", f"Не удалось проверить обновления:\n{e}")
        return False

def perform_update():
    """Загружает новые файлы и запускает скрипт замены."""
    try:
        if getattr(sys, 'frozen', False):
            base_dir = os.path.dirname(sys.executable)
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))

        downloaded = []  # временные файлы с расширением .new

        for filename in FILES_TO_UPDATE:
            url = BASE_RAW_URL + filename
            local_path = os.path.join(base_dir, filename)
            new_path = local_path + ".new"

            response = requests.get(url, timeout=30)
            if response.status_code != 200:
                mb.showerror("Ошибка", f"Не удалось загрузить {filename}")
                # удаляем уже скачанные временные файлы
                for f in downloaded:
                    try:
                        os.remove(f)
                    except:
                        pass
                return

            with open(new_path, "wb") as f:
                f.write(response.content)
            downloaded.append(new_path)

        # Создаём bat-скрипт для замены файлов
        bat_file = os.path.join(base_dir, "updater_script.bat")
        with open(bat_file, "w", encoding="utf-8-sig") as f:
            f.write("@echo off\n")
            f.write("chcp 65001 > nul\n")
            f.write("timeout /t 2 /nobreak > nul\n")
            for filename in FILES_TO_UPDATE:
                local_path = os.path.join(base_dir, filename)
                new_path = local_path + ".new"
                f.write(f'del "{local_path}"\n')
                f.write(f'ren "{new_path}" "{filename}"\n')
            # Запускаем обновлённое приложение
            main_path = os.path.join(base_dir, "Launcher.exe")
            f.write(f'start "" "{main_path}"\n')
            f.write('del "%~f0"\n')

        mb.showinfo("Обновление", "Программа будет перезагружена для применения изменений.")
        os.startfile(bat_file)
        sys.exit()

    except Exception as e:
        mb.showerror("Ошибка", f"Не удалось выполнить обновление:\n{e}")

# --- Главное меню ---
class MainMenu(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Управление оборудованием")
        self.geometry("850x600")
        
        self.center_window()
        self.init_ui()
        
        # Автоматическая проверка обновлений при запуске (тихо, без сообщения об актуальности)
        self.after(1000, lambda: check_for_updates(silent=True))
        
    def center_window(self):
        self.update_idletasks()
        width = 850
        height = 600
        x = (self.winfo_screenwidth() // 2) - (width // 2)
        y = (self.winfo_screenheight() // 2) - (height // 2)
        self.geometry(f'{width}x{height}+{x}+{y}')
        self.resizable(False, False)
        
    def init_ui(self):
        title_label = ctk.CTkLabel(
            self,
            text="Выберите раздел",
            font=ctk.CTkFont(size=28, weight="bold")
        )
        title_label.pack(pady=40)
        
        tiles_frame = ctk.CTkFrame(self, fg_color="transparent")
        tiles_frame.pack(expand=True, padx=40, pady=20)
        
        tiles_container = ctk.CTkFrame(tiles_frame, fg_color="transparent")
        tiles_container.pack(expand=True)
        
        # Плитка "Оборудование"
        equipment_tile = ctk.CTkFrame(
            tiles_container,
            width=300,
            height=180,
            corner_radius=25,
            fg_color="#1e3a8a",
            border_width=3,
            border_color="#3b82f6"
        )
        equipment_tile.grid(row=0, column=0, padx=30, pady=20)
        equipment_tile.pack_propagate(False)
        
        equipment_icon = ctk.CTkLabel(
            equipment_tile,
            text="🖥️",
            font=ctk.CTkFont(size=50)
        )
        equipment_icon.pack(pady=(30, 15))
        
        equipment_label = ctk.CTkLabel(
            equipment_tile,
            text="Оборудование",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        equipment_label.pack()
        
        equipment_tile.bind("<Enter>", lambda e: equipment_tile.configure(fg_color="#2563eb"))
        equipment_tile.bind("<Leave>", lambda e: equipment_tile.configure(fg_color="#1e3a8a"))
        equipment_tile.bind("<Button-1>", lambda e: self.open_equipment())
        
        equipment_icon.bind("<Button-1>", lambda e: self.open_equipment())
        equipment_label.bind("<Button-1>", lambda e: self.open_equipment())
        
        # Плитка "Картриджи"
        cartridge_tile = ctk.CTkFrame(
            tiles_container,
            width=300,
            height=180,
            corner_radius=25,
            fg_color="#7c2d12",
            border_width=3,
            border_color="#f97316"
        )
        cartridge_tile.grid(row=0, column=1, padx=30, pady=20)
        cartridge_tile.pack_propagate(False)
        
        cartridge_icon = ctk.CTkLabel(
            cartridge_tile,
            text="🖨️",
            font=ctk.CTkFont(size=50)
        )
        cartridge_icon.pack(pady=(30, 15))
        
        cartridge_label = ctk.CTkLabel(
            cartridge_tile,
            text="Картриджи",
            font=ctk.CTkFont(size=20, weight="bold")
        )
        cartridge_label.pack()
        
        cartridge_tile.bind("<Enter>", lambda e: cartridge_tile.configure(fg_color="#ea580c"))
        cartridge_tile.bind("<Leave>", lambda e: cartridge_tile.configure(fg_color="#7c2d12"))
        cartridge_tile.bind("<Button-1>", lambda e: self.open_cartridges())
        
        cartridge_icon.bind("<Button-1>", lambda e: self.open_cartridges())
        cartridge_label.bind("<Button-1>", lambda e: self.open_cartridges())
        
        # Кнопки управления
        buttons_frame = ctk.CTkFrame(self, fg_color="transparent")
        buttons_frame.pack(pady=30)
        
        # Кнопка "Проверить обновления"
        update_button = ctk.CTkButton(
            buttons_frame,
            text="🔄 Проверить обновления",
            command=lambda: check_for_updates(silent=False),
            fg_color="#4b5563",
            hover_color="#374151",
            width=140,
            height=35
        )
        update_button.pack(side="left", padx=10)
        
        minimize_button = ctk.CTkButton(
            buttons_frame,
            text="Свернуть",
            command=self.minimize_window,
            fg_color="#4b5563",
            hover_color="#374151",
            width=120,
            height=35
        )
        minimize_button.pack(side="left", padx=10)
        
        exit_button = ctk.CTkButton(
            buttons_frame,
            text="Выход",
            command=self.exit_app,
            fg_color="#dc2626",
            hover_color="#b91c1c",
            width=120,
            height=35
        )
        exit_button.pack(side="left", padx=10)
    
    def open_equipment(self):
        self.withdraw()
        equipment_window = EquipmentWindow(self)
        equipment_window.protocol("WM_DELETE_WINDOW", 
                                 lambda: self.on_child_close(equipment_window))
    
    def open_cartridges(self):
        self.withdraw()
        cartridge_window = CartridgeWindow(self)
        cartridge_window.protocol("WM_DELETE_WINDOW", 
                                 lambda: self.on_child_close(cartridge_window))
    
    def on_child_close(self, child_window):
        child_window.destroy()
        self.deiconify()
    
    def minimize_window(self):
        self.iconify()
    
    def exit_app(self):
        if mb.askyesno("Выход", "Вы уверены, что хотите выйти?"):
            self.destroy()

if __name__ == "__main__":
    app = MainMenu()
    app.mainloop()