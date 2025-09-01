import customtkinter as ctk
import tkinter.messagebox as mb
import sys
import os
import socket
import json
import getpass
import tempfile
import shutil
import datetime
import subprocess
import threading

from tkinter import ttk
from PIL import Image, ImageTk
from bd import Database

# === ДОБАВЛЕНО: зависимости автообновления ===
import requests

# ====== НАСТРОЙКИ АВТООБНОВЛЕНИЯ ======
CURRENT_VERSION = "1.0.0"  # <-- ОБНОВЛЯЙТЕ ПРИ КАЖДОЙ СБОРКЕ
UPDATE_JSON_URL = "https://example.com/version.json"  # <-- ЗАМЕНИТЕ НА ВАШ URL


ctk.set_appearance_mode("dark")  # dark / light / system
ctk.set_default_color_theme("dark-blue")  # варианты: dark-blue, green, blue


class App(ctk.CTk):
    def __init__(self):
        super().__init__()
        self.title("Equipment Management")
        self.attributes('-fullscreen', True)
        self.db = Database()
        self.load_config()  # Загружаем конфигурацию при запуске
        self.init_ui()
        self.new_window = None

        # === ДОБАВЛЕНО: тихая проверка обновлений через 2 сек после старта ===
        self.after(2000, self.check_for_update_silent)

    # ================== АВТООБНОВЛЕНИЕ: УТИЛИТЫ ==================
    @staticmethod
    def _parse_version(v: str):
        """Превращает '1.2.3' в кортеж (1,2,3) для корректного сравнения."""
        try:
            return tuple(int(x) for x in v.strip().split("."))
        except Exception:
            return (0,)

    @staticmethod
    def _get_app_dir():
        """Папка, где лежит exe/скрипт (учтён PyInstaller)."""
        if getattr(sys, 'frozen', False):
            return os.path.dirname(sys.executable)
        return os.path.dirname(os.path.abspath(__file__))

    @staticmethod
    def _get_self_path():
        """Полный путь к текущему exe/скрипту."""
        if getattr(sys, 'frozen', False):
            return sys.executable
        return os.path.abspath(sys.argv[0])

    def _show_progress_window(self, title="Загрузка обновления"):
        """Окно с прогресс-баром."""
        win = ctk.CTkToplevel(self)
        win.title(title)
        win.geometry("450x160")
        win.attributes('-topmost', 1)

        lbl = ctk.CTkLabel(win, text="Подключение...")
        lbl.pack(pady=(20, 10))

        pbar = ctk.CTkProgressBar(win)
        pbar.pack(fill="x", padx=20, pady=10)
        pbar.set(0)

        status = ctk.CTkLabel(win, text="0%")
        status.pack(pady=(0, 10))

        cancel_flag = {"stop": False}

        def cancel():
            cancel_flag["stop"] = True
            try:
                win.destroy()
            except:
                pass

        btn = ctk.CTkButton(win, text="Отмена", command=cancel, fg_color="#8B0000", hover_color="#A52A2A")
        btn.pack(pady=5)

        return win, pbar, lbl, status, cancel_flag

    def _write_and_run_updater(self, downloaded_path: str):
        """
        Создаёт батник, который дождётся закрытия текущего процесса,
        заменит exe и перезапустит обновлённую программу.
        """
        app_dir = self._get_app_dir()
        target_path = self._get_self_path()
        bat_path = os.path.join(app_dir, "update_run.bat")

        # ВАЖНО: используем бесконечную попытку MOVE, пока файл занят.
        bat_content = rf"""@echo off
setlocal
set SOURCE="{downloaded_path}"
set TARGET="{target_path}"

REM Ждем, пока файл освободится и удастся переместить
:wait
move /Y %SOURCE% %TARGET% >nul 2>&1
if errorlevel 1 (
  timeout /t 1 >nul
  goto wait
)
start "" "%TARGET%"
del "%~f0"
"""

        with open(bat_path, "w", encoding="utf-8") as f:
            f.write(bat_content)

        # Запускаем батник и выходим из приложения
        try:
            subprocess.Popen(['cmd', '/c', bat_path], close_fds=True, creationflags=subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0)
        except Exception:
            # запасной вариант
            subprocess.Popen(['cmd', '/c', bat_path])
        self.exit_app()

    # ================== АВТООБНОВЛЕНИЕ: ОСНОВНЫЕ МЕТОДЫ ==================
    def check_for_update_ui(self):
        """Ручная проверка через кнопку — с диалогами."""
        threading.Thread(target=self._check_for_update_internal, args=(True,), daemon=True).start()

    def check_for_update_silent(self):
        """Тихая проверка при старте — без модалок, только при наличии апдейта спросим."""
        threading.Thread(target=self._check_for_update_internal, args=(False,), daemon=True).start()

    def _check_for_update_internal(self, verbose: bool):
        try:
            if verbose:
                self.show_info("Обновления", "Проверка доступных обновлений...")
            r = requests.get(UPDATE_JSON_URL, timeout=10)
            r.raise_for_status()
            data = r.json()

            latest = str(data.get("version", "")).strip()
            url = str(data.get("url", "")).strip()
            notes = str(data.get("notes", "")).strip()

            if not latest or not url:
                if verbose:
                    mb.showerror("Обновления", "Некорректный файл версии.")
                return

            if self._parse_version(latest) > self._parse_version(CURRENT_VERSION):
                msg = f"Доступна новая версия {latest} (у вас {CURRENT_VERSION}).\n\nИзменения:\n{notes or '—'}\n\nУстановить сейчас?"
                if mb.askyesno("Обновление доступно", msg):
                    self._download_and_update(url, latest)
            else:
                if verbose:
                    self.show_info("Обновления", f"У вас актуальная версия ({CURRENT_VERSION}).")
        except Exception as e:
            if verbose:
                mb.showerror("Обновления", f"Не удалось проверить обновления:\n{e}")

    def _download_and_update(self, url: str, latest_version: str):
        win, pbar, lbl, status, cancel_flag = self._show_progress_window()

        def worker():
            try:
                with requests.get(url, stream=True, timeout=20) as resp:
                    resp.raise_for_status()
                    total = int(resp.headers.get("content-length", 0))
                    app_dir = self._get_app_dir()
                    tmp_name = f"update_{latest_version}.exe"
                    tmp_path = os.path.join(app_dir, tmp_name)

                    downloaded = 0
                    chunk_size = 1024 * 256  # 256 KB

                    lbl.configure(text="Загрузка...")
                    with open(tmp_path, "wb") as f:
                        for chunk in resp.iter_content(chunk_size=chunk_size):
                            if cancel_flag["stop"]:
                                try:
                                    f.close()
                                except:
                                    pass
                                try:
                                    if os.path.exists(tmp_path):
                                        os.remove(tmp_path)
                                except:
                                    pass
                                return
                            if chunk:
                                f.write(chunk)
                                downloaded += len(chunk)
                                if total > 0:
                                    frac = downloaded / total
                                    pbar.set(frac)
                                    status.configure(text=f"{int(frac*100)}% ({downloaded//1024} / {total//1024} KB)")
                                else:
                                    # если сервер не отдал размер, просто «крутилку»
                                    current = pbar._value if hasattr(pbar, "_value") else 0
                                    nxt = current + 0.01
                                    pbar.set(0 if nxt > 1 else nxt)
                                    status.configure(text=f"{downloaded//1024} KB")

                    lbl.configure(text="Подготовка к установке...")
                    # Закрываем окно прогресса и запускаем обновление
                    try:
                        win.destroy()
                    except:
                        pass
                    self._write_and_run_updater(tmp_path)

            except Exception as e:
                try:
                    win.destroy()
                except:
                    pass
                mb.showerror("Обновление", f"Не удалось загрузить обновление:\n{e}")

        threading.Thread(target=worker, daemon=True).start()

    # ================== ВАШИ СУЩЕСТВУЮЩИЕ МЕТОДЫ ==================
    def load_config(self):
        """Загружаем конфигурацию из файла или используем значения по умолчанию"""
        self.config_file = "app_config.json"
        default_config = {
            "show_notifications": True,
            "show_issue_notifications": True
        }
        
        try:
            if os.path.exists(self.config_file):
                with open(self.config_file, 'r') as f:
                    self.config = json.load(f)
            else:
                self.config = default_config
        except:
            self.config = default_config
    

    def save_config(self):
        """Сохраняем конфигурацию в файл"""
        try:
            with open(self.config_file, 'w') as f:
                json.dump(self.config, f)
        except Exception as e:
            print(f"Ошибка сохранения конфигурации: {e}")
    
    def show_info(self, title, message):
        """Показываем информационное сообщение, если включены уведомления"""
        if self.config["show_notifications"]:
            mb.showinfo(title, message)
    
    def show_issue_info(self, title, message):
        """Показываем сообщение о выдаче, если включены соответствующие уведомления"""
        if self.config["show_issue_notifications"]:
            mb.showinfo(title, message)
    
    def init_ui(self):
        self.tabview = ctk.CTkTabview(self)
        self.tabview.pack(fill="both", expand=True, padx=20, pady=20)
        
        self.tabview.add("Добавить/Удалить")
        self.tabview.add("Вывести данные")
        
        self.init_buttons()
        self.init_add_delete_tab()
        self.init_output_tab()

        # Лейбл даты/времени
        # уже переносился ниже в init_add_delete_tab -> оставляем там
    
    def init_buttons(self):
        self.button_frame = ctk.CTkFrame(self)
        self.button_frame.pack(pady=5, padx=5)
        
        self.exit_button = ctk.CTkButton(
            self.button_frame, text="Выйти", command=self.exit_app,
            fg_color="red", hover_color="darkred"
        )
        self.reload_button = ctk.CTkButton(
            self.button_frame, text="Перезагрузить", command=self.reload_app,
            fg_color="blue", hover_color="darkblue"
        )
        self.minimize_button = ctk.CTkButton(
            self.button_frame, text="Свернуть", command=self.minimize_app,
            fg_color="gray", hover_color="darkgray"
        )
        
        self.exit_button.pack(side="left", padx=10)
        self.reload_button.pack(side="left", padx=10)
        self.minimize_button.pack(side="left", padx=10)
    
    def init_add_delete_tab(self):
        main_frame = ctk.CTkFrame(self.tabview.tab("Добавить/Удалить"))
        main_frame.pack(fill="both", expand=True, pady=20, padx=20)
        
        # Левая панель для добавления данных
        left_frame = ctk.CTkFrame(main_frame)
        left_frame.pack(side="left", fill="both", expand=True, padx=(0, 10))
        
        # Правая панель для удаления данных
        right_frame = ctk.CTkFrame(main_frame, width=400)
        right_frame.pack(side="right", fill="y", padx=(10, 0))
        right_frame.pack_propagate(False)  # Фиксируем ширину
        
        # Верхняя часть левой панели - настройки
        settings_frame = ctk.CTkFrame(left_frame)
        settings_frame.pack(fill="x", pady=(0, 10))
        
    
        ctk.CTkLabel(settings_frame, text="Настройки уведомлений", 
                     font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # Чекбокс для обычных уведомлений
        self.notify_var = ctk.BooleanVar(value=self.config["show_notifications"])
        notify_check = ctk.CTkCheckBox(
            settings_frame, text="Показывать уведомления",
            variable=self.notify_var,
            command=self.toggle_notifications
        )
        notify_check.pack(pady=5, padx=10, anchor="w")
        
        # Чекбокс для уведомлений о выдаче
        self.issue_notify_var = ctk.BooleanVar(value=self.config["show_issue_notifications"])
        issue_notify_check = ctk.CTkCheckBox(
            settings_frame, text="Показывать уведомления о выдаче",
            variable=self.issue_notify_var,
            command=self.toggle_issue_notifications
        )
        issue_notify_check.pack(pady=5, padx=10, anchor="w")
        

        # Кнопка сохранения настроек
        ctk.CTkButton(
            settings_frame, text="Сохранить настройки", 
            command=self.save_settings,
            fg_color="#2E8B57", hover_color="#3CB371"
        ).pack(pady=15)
        
        # Нижняя часть левой панели - добавление данных
        data_frame = ctk.CTkFrame(left_frame)
        data_frame.pack(fill="both", expand=True)
        
        # Equipment Section
        equip_frame = ctk.CTkFrame(data_frame)
        equip_frame.pack(side="left", fill="both", expand=True, padx=(0, 5))
        
        ctk.CTkLabel(equip_frame, text="ОБОРУДОВАНИЕ", font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        fields = [
            ("Дата (ДД.ММ.ГГГГ)", "date_entry"),
            ("Номер n/n", "nomer_entry"),
            ("Заявка", "application_entry"),
            ("Подразделение", "division_entry"),
            ("Инв. номер", "inv_entry"),
            ("Модель", "model_entry"),
            ("Сдал", "zdal_entry")
        ]
        
        self.equipment_entries = {}
        for label, name in fields:
            frame = ctk.CTkFrame(equip_frame)
            frame.pack(fill="x", padx=5, pady=2)
            
            ctk.CTkLabel(frame, text=label, width=120).pack(side="left")
            entry = ctk.CTkEntry(frame)
            entry.pack(side="right", fill="x", expand=True, padx=(5, 0))
            self.equipment_entries[name] = entry
        
        ctk.CTkButton(
            equip_frame, text="Добавить оборудование", 
            command=self.add_equipment,
            fg_color="#A81FF8", hover_color="#510461"
        ).pack(pady=10)
        
        # Cartridges Section
        cart_frame = ctk.CTkFrame(data_frame)
        cart_frame.pack(side="right", fill="both", expand=True, padx=(5, 0))
        
        ctk.CTkLabel(cart_frame, text="КАРТРИДЖИ", font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        self.cartridge_entries = {}
        for label, name in fields:
            frame = ctk.CTkFrame(cart_frame)
            frame.pack(fill="x", padx=5, pady=2)
            
            ctk.CTkLabel(frame, text=label, width=120).pack(side="left")
            entry = ctk.CTkEntry(frame)
            entry.pack(side="right", fill="x", expand=True, padx=(5, 0))
            self.cartridge_entries[name] = entry
        
        ctk.CTkButton(
            cart_frame, text="Добавить картридж", 
            command=self.add_cartridge,
            fg_color="#A81FF8", hover_color="#510461"
        ).pack(pady=10)
        
        # Issue Section
        issue_frame = ctk.CTkFrame(left_frame)
        issue_frame.pack(fill="x", pady=(10, 0))
        
        ctk.CTkLabel(issue_frame, text="ВЫДАЧА ОБОРУДОВАНИЯ И КАРТРИДЖЕЙ", 
                    font=ctk.CTkFont(weight="bold")).pack(pady=5)
        
        # Equipment Issue
        equip_issue_frame = ctk.CTkFrame(issue_frame)
        equip_issue_frame.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(equip_issue_frame, text="Оборудование ID:", width=120).pack(side="left")
        self.equip_id_entry = ctk.CTkEntry(equip_issue_frame, width=80)
        self.equip_id_entry.pack(side="left", padx=2)
        
        ctk.CTkLabel(equip_issue_frame, text="Дата:", width=50).pack(side="left", padx=(10, 0))
        self.equip_date_entry = ctk.CTkEntry(equip_issue_frame, width=100)
        self.equip_date_entry.pack(side="left", padx=2)
        
        ctk.CTkLabel(equip_issue_frame, text="ФИО:", width=50).pack(side="left", padx=(10, 0))
        self.equip_fio_entry = ctk.CTkEntry(equip_issue_frame)
        self.equip_fio_entry.pack(side="left", fill="x", expand=True, padx=2)
    
        ctk.CTkButton(
            equip_issue_frame, text="Выдать", width=80,
            command=lambda: self.issue_item("equipment"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="right", padx=(5, 0))
        
        # Cartridge Issue
        cart_issue_frame = ctk.CTkFrame(issue_frame)
        cart_issue_frame.pack(fill="x", padx=5, pady=2)
        
        ctk.CTkLabel(cart_issue_frame, text="Картридж ID:", width=120).pack(side="left")
        self.cart_id_entry = ctk.CTkEntry(cart_issue_frame, width=80)
        self.cart_id_entry.pack(side="left", padx=2)
        
        ctk.CTkLabel(cart_issue_frame, text="Дата:", width=50).pack(side="left", padx=(10, 0))
        self.cart_date_entry = ctk.CTkEntry(cart_issue_frame, width=100)
        self.cart_date_entry.pack(side="left", padx=2)
        
        ctk.CTkLabel(cart_issue_frame, text="ФИО:", width=50).pack(side="left", padx=(10, 0))
        self.cart_fio_entry = ctk.CTkEntry(cart_issue_frame)
        self.cart_fio_entry.pack(side="left", fill="x", expand=True, padx=2)
        
        ctk.CTkButton(
            cart_issue_frame, text="Выдать", width=80,
            command=lambda: self.issue_item("cartridge"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="right", padx=(5, 0))
        
        # Log Section
        log_frame = ctk.CTkFrame(left_frame)
        log_frame.pack(fill="both", expand=True, pady=(10, 0))
        
        ctk.CTkLabel(log_frame, text="ЖУРНАЛ ОПЕРАЦИЙ", font=ctk.CTkFont(weight="bold")).pack(pady=5)
        self.results_text_log = ctk.CTkTextbox(log_frame, wrap="word", height=100)
        self.results_text_log.pack(fill="both", expand=True, padx=5, pady=(0, 5))
        
        # Правая панель - удаление данных
        ctk.CTkLabel(right_frame, text="УПРАВЛЕНИЕ ДАННЫМИ", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)
        
        # Equipment deletion
        equip_del_frame = ctk.CTkFrame(right_frame)
        equip_del_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(equip_del_frame, text="Удаление оборудования", 
                    font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        del_equip_frame = ctk.CTkFrame(equip_del_frame)
        del_equip_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(del_equip_frame, text="ID:").pack(side="left")
        self.del_equip_id = ctk.CTkEntry(del_equip_frame, width=80)
        self.del_equip_id.pack(side="left", padx=5)
        
        ctk.CTkButton(
            del_equip_frame, text="Удалить", width=80,
            command=lambda: self.delete_item("equipment"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="right")
        
        # Cartridge deletion
        cart_del_frame = ctk.CTkFrame(right_frame)
        cart_del_frame.pack(fill="x", padx=10, pady=5)
        
        ctk.CTkLabel(cart_del_frame, text="Удаление картриджей", 
                    font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        del_cart_frame = ctk.CTkFrame(cart_del_frame)
        del_cart_frame.pack(fill="x", pady=5)
        
        ctk.CTkLabel(del_cart_frame, text="ID:").pack(side="left")
        self.del_cart_id = ctk.CTkEntry(del_cart_frame, width=80)
        self.del_cart_id.pack(side="left", padx=5)
        
        ctk.CTkButton(
            del_cart_frame, text="Удалить", width=80,
            command=lambda: self.delete_item("cartridge"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="right")
        
        # Mass deletion
        mass_del_frame = ctk.CTkFrame(right_frame)
        mass_del_frame.pack(fill="x", padx=10, pady=15)
        
        ctk.CTkLabel(mass_del_frame, text="Массовое удаление", 
                    font=ctk.CTkFont(weight="bold")).pack(anchor="w")
        
        ctk.CTkLabel(mass_del_frame, text="Пароль для подтверждения:").pack(anchor="w", pady=(5, 0))
        self.del_password = ctk.CTkEntry(mass_del_frame, show="*")
        self.del_password.pack(fill="x", pady=5)
        
        mass_btn_frame = ctk.CTkFrame(mass_del_frame)
        mass_btn_frame.pack(fill="x", pady=5)
        
        ctk.CTkButton(
            mass_btn_frame, text="Удалить всё оборудование",
            command=lambda: self.delete_all("equipment"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(fill="x", pady=2, padx=5)
        
        ctk.CTkButton(
            mass_btn_frame, text="Удалить все картриджи",
            command=lambda: self.delete_all("cartridge"),
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(fill="x", pady=2, padx=5)
        
        # ПРОЧИЕ
        ctk.CTkLabel(right_frame, text="ПРОЧИЕ", 
                    font=ctk.CTkFont(size=16, weight="bold")).pack(pady=10)

        temp_frame = ctk.CTkFrame(right_frame)
        temp_frame.pack(fill="x", padx=10, pady=15)

        ctk.CTkButton(
            temp_frame, text="очистить TEMP", width=80,
            command=self.temp_delete,
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            temp_frame, text="изменить данные", width=80,
            command=self.change,
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="left", padx=5)

        ctk.CTkButton(
            temp_frame, text="очистить журнал", width=80,
            command=self.delete_magazine,
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="left", padx=5, pady=5)

        app_frame = ctk.CTkFrame(right_frame)
        app_frame.pack(fill="x", padx=10, pady=15)

        ctk.CTkButton(
            app_frame, text="app", width=80,
            command=self.app_btn,
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="left", padx=5, pady=5)

        # === ДОБАВЛЕНО: кнопка «Проверить обновления» ===
        ctk.CTkButton(
            app_frame, text="Проверить обновления", width=140,
            command=self.check_for_update_ui,
            fg_color="#2E8B57", hover_color="#3CB371"
        ).pack(side="left", padx=6, pady=5)

        datetime_btn_frame = ctk.CTkFrame(right_frame)
        datetime_btn_frame.pack(fill="x", padx=10, pady=15)

        # Лейбл даты/времени
        self.datetime_label = ctk.CTkLabel(
            datetime_btn_frame, text="",
            font=ctk.CTkFont(size=22, weight="bold"),
            text_color="#EAEAEA"
        )
        self.datetime_label.pack(side="right", padx=5)
        self.update_datetime()  # Запускаем обновление времени
    
    def update_datetime(self):
        """Обновляет дату и время каждую секунду"""
        now = datetime.datetime.now()
        formatted = f"SIDE  📅 {now.strftime('%d.%m.%Y')}   ⏰ {now.strftime('%H:%M:%S')}"
        self.datetime_label.configure(text=formatted)
        self.after(1000, self.update_datetime)

    def toggle_notifications(self):
        """Обновляем конфигурацию для обычных уведомлений"""
        self.config["show_notifications"] = self.notify_var.get()
    
    def toggle_issue_notifications(self):
        """Обновляем конфигурацию для уведомлений о выдаче"""
        self.config["show_issue_notifications"] = self.issue_notify_var.get()
    
    def save_settings(self):
        """Сохраняем настройки и показываем подтверждение"""
        self.config["show_notifications"] = self.notify_var.get()
        self.config["show_issue_notifications"] = self.issue_notify_var.get()
        self.save_config()
        if self.config["show_notifications"]:
            mb.showinfo("Сохранено", "Настройки успешно сохранены!")
    
    def init_output_tab(self):
        frame = ctk.CTkFrame(self.tabview.tab("Вывести данные"))
        frame.pack(pady=20, padx=20, fill="both", expand=True)

        # Search controls
        search_frame = ctk.CTkFrame(frame)
        search_frame.pack(fill="x", padx=10, pady=10)

        self.search_entry = ctk.CTkEntry(search_frame, placeholder_text="Поиск...", width=300)
        self.search_entry.pack(side="left", padx=5, pady=5)

        self.search_type = ctk.CTkOptionMenu(
            search_frame,
            values=["Оборудование", "Картриджи"]
        )
        self.search_type.pack(side="left", padx=5, pady=5)

        self.search_by = ctk.CTkOptionMenu(
            search_frame,
            values=["ID", "Номер n/n", "Инв. номер", "Подразделение", "Заявка", "Модель"]
        )
        self.search_by.pack(side="left", padx=5, pady=5)

        ctk.CTkButton(
            search_frame, text="Найти",
            command=self.search_items,
            fg_color="#A81FF8", hover_color="#510461"
        ).pack(side="left", padx=5, pady=5)

        ctk.CTkButton(
            search_frame, text="Показать все",
            command=self.show_all_items,
            fg_color="#3340F0", hover_color="#0059FF"
        ).pack(side="left", padx=5, pady=5)

        # === Новый блок для Treeview ===
        tree_frame = ctk.CTkFrame(frame)
        tree_frame.pack(fill="both", expand=True, padx=10, pady=10)

        self.columns = [
            "ID", "Дата", "Номер n/n", "Заявка", "Подразделение",
            "Инв.номер", "Модель", "Сдал", "Дата выдачи", "ФИО выдачи"
        ]

        self.tree = ttk.Treeview(tree_frame, columns=self.columns, show="headings", height=20)

        for col in self.columns:
            self.tree.heading(col, text=col)
            self.tree.column(col, width=120, anchor="w")

        # Скроллбары
        scroll_y = ttk.Scrollbar(tree_frame, orient="vertical", command=self.tree.yview)
        scroll_x = ttk.Scrollbar(tree_frame, orient="horizontal", command=self.tree.xview)
        self.tree.configure(yscroll=scroll_y.set, xscroll=scroll_x.set)

        self.tree.grid(row=0, column=0, sticky="nsew")
        scroll_y.grid(row=0, column=1, sticky="ns")
        scroll_x.grid(row=1, column=0, sticky="ew")

        tree_frame.grid_rowconfigure(0, weight=1)
        tree_frame.grid_columnconfigure(0, weight=1)

        # Применим тёмный стиль для Treeview
        self.set_dark_treeview_style()
    
    def set_dark_treeview_style(self):
        style = ttk.Style()
        style.theme_use("clam")  # чтобы применялись цвета
        style.configure("Treeview",
                        background="#2d2d2d",
                        foreground="white",
                        fieldbackground="#2d2d2d",
                        rowheight=28)
        style.map('Treeview',
                  background=[('selected', '#4a6984')])

        style.configure("Treeview.Heading",
                        background="#1e1e1e",
                        foreground="white",
                        font=("Arial", 11, "bold"))


    # Database operations
    def add_equipment(self):
        data = [entry.get() for entry in self.equipment_entries.values()]
        if not any(data):
            mb.showerror("Ошибка", "Заполните все поля!")
            return
        
        self.db.add_equipment(*data)
        self.show_info("Успех", "Оборудование добавлено!")
        self.clear_entries(self.equipment_entries.values())
        results = self.db.add_equipment_log()
        self.results_text_log.insert("end", f"оборудование - {results} {data}\n")
    
    def add_cartridge(self):
        data = [entry.get() for entry in self.cartridge_entries.values()]
        if not any(data):
            mb.showerror("Ошибка", "Заполните все поля!")
            return
        
        self.db.add_cartridge(*data)
        self.show_info("Успех", "Картридж добавлен!")
        self.clear_entries(self.cartridge_entries.values())
        results = self.db.add_cartridges_log()
        self.results_text_log.insert("end", f"картридж - {results} {data}\n")


    def issue_item(self, item_type):
        if item_type == "equipment":
            id = self.equip_id_entry.get()
            date = self.equip_date_entry.get()
            fio = self.equip_fio_entry.get()
        else:
            id = self.cart_id_entry.get()
            date = self.cart_date_entry.get()
            fio = self.cart_fio_entry.get()
        
        if not any([id, date, fio]):
            mb.showerror("Ошибка", "Заполните все поля!")
            return
        
        if item_type == "equipment":
            self.db.update_equipment(id, date, fio)
        else:
            self.db.update_cartridge(id, date, fio)
        
        self.show_issue_info("Успех", "Запись обновлена!")
        if item_type == "equipment":
            self.clear_entries([self.equip_id_entry, self.equip_date_entry, self.equip_fio_entry])
            self.results_text_log.insert("end", f"""оборудование - {id} ДАТА:{date} | ФИО:{fio}\n""")
        else:
            self.clear_entries([self.cart_id_entry, self.cart_date_entry, self.cart_fio_entry])
            self.results_text_log.insert("end", f"""картридж - {id} ДАТА:{date} | ФИО:{fio}\n""")

    def delete_item(self, item_type):
        if item_type == "equipment":
            id = self.del_equip_id.get()
            func = self.db.delete_equipment
            self.results_text_log.insert("end", f" удалено оборудывание {id}\n")
        else:
            id = self.del_cart_id.get()
            func = self.db.delete_cartridge
            self.results_text_log.insert("end", f"удалён картридж {id}\n")
        if not id:
            mb.showerror("Ошибка", "Введите ID!")
            return
        
        if mb.askyesno("Подтверждение", "Удалить запись?"):
            func(id)
            self.show_info("Успех", "Запись удалена!")
            if item_type == "equipment":
                self.del_equip_id.delete(0, "end")
            else:
                self.del_cart_id.delete(0, "end")
    
    def delete_all(self, item_type):
        password = self.del_password.get()
        if password != "246942":
            mb.showerror("Ошибка", "Неверный пароль!")
            return
        
        if mb.askyesno("Подтверждение", "Удалить ВСЕ данные?"):
            if item_type == "equipment":
                self.db.delete_all_equipment()
            else:
                self.db.delete_all_cartridges()
            self.show_info("Успех", "Данные удалены!")
        self.del_password.delete(0, "end")
    
    def search_items(self):
        search_term = self.search_entry.get()
        item_type = self.search_type.get()
        search_by = self.search_by.get()

        column_map = {
            "ID": "id",
            "Номер n/n": "nomer_n_n",
            "Инв. номер": "inv",
            "Подразделение": "division",
            "Заявка": "application",
            "Модель": "model"
        }

        column = column_map.get(search_by, "id")

        if search_term:
            if item_type == "Оборудование":
                results = self.db.get_equipment_by(column, search_term)
            else:
                results = self.db.get_cartridge_by(column, search_term)
        else:
            results = self.db.get_all_equipment() if item_type == "Оборудование" else self.db.get_all_cartridges()

        self.display_results(results)
    
    def show_all_items(self):
        item_type = self.search_type.get()
        if item_type == "Оборудование":
            results = self.db.get_all_equipment()
        else:
            results = self.db.get_all_cartridges()

        self.display_results(results)

    def display_results(self, results):
        # Очистка перед выводом
        for row in self.tree.get_children():
            self.tree.delete(row)

        # Добавляем новые строки
        for row in results:
            self.tree.insert("", "end", values=row)
    

    def temp_delete(self):
        def clear_temp_folder():
            self.results_text_log.insert("0.0", f"""Очищает системную временную папку и выводит статистику.\n""")
            temp_folder = tempfile.gettempdir()  # Get the system's temp directory
            deleted_files_count = 0
            deleted_size_mb = 0.0

            if not os.path.exists(temp_folder):
                    self.results_text_log.insert("0.0", f"Временная папка не найдена: {temp_folder}\n")
                    return
            try:
                    for filename in os.listdir(temp_folder):
                            file_path = os.path.join(temp_folder, filename)
                            try:
                                    if os.path.isfile(file_path):
                                            file_size_bytes = os.path.getsize(file_path)
                                            os.remove(file_path)
                                            self.results_text_log.insert("0.0", f"Удаленный файл: {file_path}\n")
                                            deleted_files_count += 1
                                            deleted_size_mb += file_size_bytes / (1024 * 1024)  # Convert bytes to MB
                                    elif os.path.isdir(file_path):
                                            shutil.rmtree(file_path)
                                            self.results_text_log.insert("0.0", f"Удаленный каталог: {file_path}\n")
                                            # NOTE: Size of directory is harder to calculate here efficiently
                                            deleted_files_count += sum([len(files) for r, d, files in os.walk(file_path)]) # Count all files in the deleted directory
                            except Exception as e:
                                    self.results_text_log.insert("0.0", f"Ошибка при удалении {file_path}: {e}\n")
            except Exception as e:
                    self.results_text_log.insert("0.0", f"Ошибка при доступе к временному каталогу: {e}\n")
                        
            self.results_text_log.insert("0.0", f"Очистка временной папки завершена.\n\n")
            self.results_text_log.insert("0.0", f"Всего удалено файлов: {deleted_files_count}\n")
            self.results_text_log.insert("0.0", f"Удаленный размер: {deleted_size_mb:.2f} MB\n")
        clear_temp_folder()


    def clear_entries(self, entries):
        for entry in entries:
            entry.delete(0, "end")
    
    def exit_app(self):
        self.save_config()
        self.destroy()
        sys.exit(0)

    def reload_app(self):
        self.save_config()
        self.destroy()
        os.execv(sys.executable, ['python'] + sys.argv)

    def minimize_app(self):
        self.iconify()

    def delete_magazine(self):
        self.results_text_log.delete("0.0", "end")


    def change(self):
        if self.new_window is None or not self.new_window.winfo_exists():
            self.new_window = ctk.CTkToplevel(self)
            self.new_window.title("Изменение данных")
            self.new_window.geometry("950x600")
            self.new_window.attributes('-topmost', 1)

            # Главный контейнер
            main_frame = ctk.CTkFrame(self.new_window)
            main_frame.pack(fill="both", expand=True, padx=10, pady=10)

            # ===== Блок для Оборудования =====
            equipment_frame = ctk.CTkFrame(main_frame)
            equipment_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(equipment_frame, text="Изменение Оборудования", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10)

            # ID
            ctk.CTkLabel(equipment_frame, text="ID:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
            self.change_id_entry = ctk.CTkEntry(equipment_frame)
            self.change_id_entry.grid(row=1, column=1, pady=3)

            self.change_fields_equip = {}
            equip_labels = {
                "date": "Дата",
                "nomer_n_n": "Номер Н/Н",
                "application": "Заявка",
                "division": "Подразделение",
                "inv": "Инвентарный номер",
                "model": "Модель",
                "zdal": "Сдал"
            }

            row = 2
            for key, label in equip_labels.items():
                ctk.CTkLabel(equipment_frame, text=f"{label}:").grid(row=row, column=0, sticky="e", padx=5, pady=3)
                entry = ctk.CTkEntry(equipment_frame)
                entry.grid(row=row, column=1, pady=3)
                self.change_fields_equip[key] = entry
                row += 1

            ctk.CTkButton(equipment_frame, text="Изменить Оборудование",
                        command=self.change_equipment_partial, fg_color="#2E8B57", hover_color="#3CB371").grid(row=row, column=0, columnspan=2, pady=10)

            # ===== Блок для Картриджей =====
            cartridges_frame = ctk.CTkFrame(main_frame)
            cartridges_frame.pack(side="left", fill="both", expand=True, padx=10, pady=10)

            ctk.CTkLabel(cartridges_frame, text="Изменение Картриджей", font=ctk.CTkFont(size=16, weight="bold")).grid(row=0, column=0, columnspan=2, pady=10)

            # ID
            ctk.CTkLabel(cartridges_frame, text="ID:").grid(row=1, column=0, sticky="e", padx=5, pady=3)
            self.change_id_entry_cartridges = ctk.CTkEntry(cartridges_frame)
            self.change_id_entry_cartridges.grid(row=1, column=1, pady=3)

            self.change_fields_cart = {}
            cart_labels = {
                "date": "Дата",
                "nomer_n_n": "Номер Н/Н",
                "application": "Заявка",
                "division": "Подразделение",
                "inv": "Инвентарный номер",
                "model": "Модель",
                "zdal": "Сдал"
            }

            row = 2
            for key, label in cart_labels.items():
                ctk.CTkLabel(cartridges_frame, text=f"{label}:").grid(row=row, column=0, sticky="e", padx=5, pady=3)
                entry = ctk.CTkEntry(cartridges_frame)
                entry.grid(row=row, column=1, pady=3)
                self.change_fields_cart[key] = entry
                row += 1

            ctk.CTkButton(cartridges_frame, text="Изменить Картридж",
                        command=self.change_cartridge_partial, fg_color="#2E8B57", hover_color="#3CB371").grid(row=row, column=0, columnspan=2, pady=10)

    

    def change_equipment_partial(self):
        id = self.change_id_entry.get()
        if not id:
            mb.showerror("Ошибка", "Введите ID!")
            return
        data = {key: entry.get() for key, entry in self.change_fields_equip.items() if entry.get().strip() != ""}
        if not data:
            mb.showerror("Ошибка", "Введите хотя бы одно значение!")
            return
        self.db.update_equipment_partial(id, data)
        self.results_text_log.insert("end", f"Изменено оборудование ID {id}: {data}\n")
        self.show_info("Успех", "Данные обновлены!")

        self.change_id_entry.delete(0, "end")
        for entry in self.change_fields_equip.values():
            entry.delete(0, "end")

    def change_cartridge_partial(self):
        id = self.change_id_entry_cartridges.get()
        if not id:
            mb.showerror("Ошибка", "Введите ID!")
            return
        data = {key: entry.get() for key, entry in self.change_fields_cart.items() if entry.get().strip() != ""}
        if not data:
            mb.showerror("Ошибка", "Введите хотя бы одно значение!")
            return
        self.db.update_cartridge_partial(id, data)
        self.results_text_log.insert("end", f"Изменен картридж ID {id}: {data}\n")
        self.show_info("Успех", "Данные обновлены!")

        self.change_id_entry_cartridges.delete(0, "end")
        for entry in self.change_fields_cart.values():
            entry.delete(0, "end")
    
    def app_btn(self):
        try:
            # Получаем абсолютный путь к текущей директории
            current_dir = os.path.dirname(os.path.abspath(__file__))
            script_path = os.path.join(current_dir, "1.py")
            
            # Проверяем существование файла
            if not os.path.exists(script_path):
                raise FileNotFoundError("Файл second.py не найден")
                
            # Запускаем файл в отдельном процессе
            subprocess.Popen(["python", script_path], shell=True)
        
        except Exception as e:
            pass


if __name__ == "__main__":
    app = App()
    app.mainloop()
