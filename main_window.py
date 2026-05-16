import os
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox

from app_links import PROJECT_URL, USER_GUIDE_URL
from app_resources import resource_path
from csv_export import save_to_csv
from field_exporter import get_fields_by_source, normalize_field, normalize_source_type
from planfix_client import check_connection, get_object_list, get_task_template_list
from searchable_dropdown import SearchableDropdown
from settings import (
    get_exports_dir,
    load_account,
    load_token,
    make_named_output_filename,
    save_account,
    save_exports_dir,
    save_token,
    validate_account,
    validate_token,
)
from version import APP_VERSION


class MainWindow:
    def __init__(self, config: dict) -> None:
        self.config = config

        self.root = tk.Tk()
        self.root.title(f"Planfix Field Exporter {APP_VERSION}")
        try:
            self.root.iconbitmap(resource_path("assets/app-icon.ico"))
        except tk.TclError:
            pass
        self.root.resizable(False, False)

        self.source_type_var = tk.StringVar(value="object")
        self.status_var = tk.StringVar(value="Выберите источник и загрузите список.")
        self.loaded_count_var = tk.StringVar(value="")
        self.account_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self.exports_dir_var = tk.StringVar()

        self.items_by_display_name: dict[str, dict] = {}
        self.all_items: list[dict] = []

        self._build_ui()
        self._load_settings()
        self._update_source_label()

        if self._has_ready_config():
            self._load_items()
        else:
            self.status_var.set("Введите аккаунт и токен, затем нажмите «Сохранить».")

    def _build_ui(self) -> None:
        frame = tk.Frame(self.root, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        settings_frame = tk.LabelFrame(frame, text="Настройки", padx=12, pady=12)
        settings_frame.grid(row=0, column=0, sticky="nsew", padx=(0, 12))

        tk.Label(settings_frame, text="Аккаунт Planfix").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        account_entry = tk.Entry(
            settings_frame,
            textvariable=self.account_var,
            width=38,
        )
        account_entry.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 4),
        )
        tk.Label(
            settings_frame,
            text="Например: engineering  (без .planfix.ru)",
            justify="left",
            fg="#555555",
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(0, 12),
        )

        tk.Label(settings_frame, text="Токен доступа").grid(
            row=3,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        token_entry = tk.Entry(
            settings_frame,
            textvariable=self.token_var,
            width=38,
            show="*",
        )
        token_entry.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(0, 4),
        )
        tk.Label(
            settings_frame,
            text="Вставьте только сам токен, без слова Bearer.",
            justify="left",
            fg="#555555",
        ).grid(
            row=5,
            column=0,
            sticky="w",
            pady=(0, 12),
        )
        tk.Label(
            settings_frame,
            text=(
                "Токен будет сохранён в системном хранилище Windows,\n"
                "а не в открытом текстовом файле."
            ),
            justify="left",
            fg="#555555",
        ).grid(
            row=6,
            column=0,
            sticky="w",
            pady=(0, 12),
        )

        tk.Label(settings_frame, text="Папка выгрузок").grid(
            row=7,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        exports_frame = tk.Frame(settings_frame)
        exports_frame.grid(row=8, column=0, sticky="ew", pady=(0, 12))

        exports_entry = tk.Entry(
            exports_frame,
            textvariable=self.exports_dir_var,
            width=32,
        )
        exports_entry.pack(side="left", fill="x", expand=True)

        tk.Button(
            exports_frame,
            text="Выбрать...",
            width=10,
            command=self._choose_exports_dir,
        ).pack(side="left", padx=(8, 0))

        tk.Button(
            exports_frame,
            text="Открыть",
            width=10,
            command=self._open_exports_dir,
        ).pack(side="left", padx=(8, 0))

        self._bind_entry_shortcuts(exports_entry)

        tk.Button(
            settings_frame,
            text="Сохранить настройки",
            width=20,
            command=self._save_settings,
        ).grid(row=9, column=0, sticky="e")

        self._bind_entry_shortcuts(account_entry)
        self._bind_entry_shortcuts(token_entry)

        work_frame = tk.Frame(frame)
        work_frame.grid(row=0, column=1, sticky="nsew")

        source_frame = tk.LabelFrame(work_frame, text="Что выгрузить", padx=12, pady=12)
        source_frame.grid(row=0, column=0, sticky="ew")

        tk.Radiobutton(
            source_frame,
            text="Поля объекта",
            variable=self.source_type_var,
            value="object",
            command=self._on_source_type_changed,
        ).grid(row=0, column=0, sticky="w")

        tk.Radiobutton(
            source_frame,
            text="Поля шаблона задачи",
            variable=self.source_type_var,
            value="task_template",
            command=self._on_source_type_changed,
        ).grid(row=1, column=0, sticky="w", pady=(6, 0))

        selection_frame = tk.LabelFrame(work_frame, text="Выбор источника", padx=12, pady=12)
        selection_frame.grid(row=1, column=0, sticky="ew", pady=(12, 0))

        self.selection_label = tk.Label(selection_frame, text="")
        self.selection_label.grid(row=0, column=0, sticky="w", pady=(0, 4))

        tk.Label(
            selection_frame,
            textvariable=self.loaded_count_var,
            justify="right",
            fg="#555555",
        ).grid(row=0, column=0, sticky="e", pady=(0, 4))

        self.selection_dropdown = SearchableDropdown(
            selection_frame,
            width=68,
        )
        self.selection_dropdown.grid(row=1, column=0, sticky="ew")

        action_frame = tk.Frame(work_frame)
        action_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        self.export_button = tk.Button(
            action_frame,
            text="Выгрузить",
            width=14,
            command=self._export_selected_item,
        )
        self.export_button.pack(side="right")

        tk.Label(
            work_frame,
            textvariable=self.status_var,
            justify="left",
            fg="#555555",
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))

        footer_frame = tk.Frame(frame)
        footer_frame.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(12, 0))

        guide_link = tk.Label(
            footer_frame,
            text="Руководство",
            fg="#0066cc",
            cursor="hand2",
        )
        guide_link.pack(side="left")
        guide_link.bind("<Button-1>", lambda _event: self._open_user_guide())

        about_link = tk.Label(
            footer_frame,
            text="О программе",
            fg="#0066cc",
            cursor="hand2",
        )
        about_link.pack(side="left", padx=(16, 0))
        about_link.bind("<Button-1>", lambda _event: self._show_about())

    def _load_settings(self) -> None:
        self.exports_dir_var.set(str(get_exports_dir()))

        account = load_account()

        if not account:
            return

        self.account_var.set(account)

        token = load_token(account)
        if token:
            self.token_var.set(token)

    def _on_source_type_changed(self) -> None:
        self.items_by_display_name.clear()
        self.all_items = []
        self.selection_dropdown.clear()
        self.loaded_count_var.set("")
        self._update_source_label()

        if self._has_ready_config():
            self._load_items()
        else:
            self.status_var.set("Сначала сохраните аккаунт и токен.")

    def _update_source_label(self) -> None:
        if self.source_type_var.get() == "object":
            self.selection_label.config(text="Объект Planfix")
        else:
            self.selection_label.config(text="Шаблон задачи Planfix")

    def _load_items(self) -> None:
        source_type = self.source_type_var.get()

        try:
            self.status_var.set("Загружаю список...")
            self.root.update_idletasks()

            if source_type == "object":
                items = get_object_list(self.config)
                id_label = "ID объекта"
            else:
                items = get_task_template_list(self.config)
                id_label = "ID шаблона"
        except Exception as error:
            self.status_var.set("Не удалось загрузить список.")
            messagebox.showerror("Ошибка", str(error))
            return

        self.all_items = sorted(
            items,
            key=lambda item: str(item.get("name", "")).casefold(),
        )
        self._apply_filter()

    def _apply_filter(self) -> None:
        source_type = self.source_type_var.get()
        if source_type == "object":
            id_label = "ID объекта"
        else:
            id_label = "ID шаблона"

        display_names = []
        self.items_by_display_name.clear()

        for item in self.all_items:
            item_id = item.get("id", "")
            item_name = item.get("name", "")
            display_name = f"{item_name} ({id_label}: {item_id})"
            display_names.append(display_name)
            self.items_by_display_name[display_name] = item

        self.selection_dropdown.set_items(display_names)

        if display_names:
            if source_type == "object":
                self.loaded_count_var.set(f"Загружено объектов: {len(display_names)}")
            else:
                self.loaded_count_var.set(f"Загружено шаблонов: {len(display_names)}")
            self.status_var.set("")
        else:
            self.selection_dropdown.clear()
            self.loaded_count_var.set("")
            self.status_var.set("Список пуст.")

    def _has_ready_config(self) -> bool:
        return bool(
            self.config.get("account")
            and self.config.get("token")
            and self.config.get("base_url")
        )

    def _export_selected_item(self) -> None:
        display_name = self.selection_dropdown.get()
        selected_item = self.items_by_display_name.get(display_name)

        if not selected_item:
            messagebox.showwarning(
                "Ничего не выбрано",
                "Сначала загрузите список и выберите нужную запись.",
            )
            return

        source_type = self.source_type_var.get()
        source_id = int(selected_item["id"])
        source_name = selected_item.get("name", "")

        try:
            self.status_var.set("Выгружаю поля...")
            self.root.update_idletasks()

            fields = get_fields_by_source(self.config, source_type, source_id)
            rows = [
                normalize_field(source_type, source_id, source_name, field)
                for field in fields
            ]

            output_file = make_named_output_filename(
                source_type,
                source_id,
                source_name,
            )
            save_to_csv(rows, output_file)
        except Exception as error:
            self.status_var.set("Не удалось выполнить выгрузку.")
            messagebox.showerror("Ошибка", str(error))
            return

        self.status_var.set(
            f"Готово. Выгружено полей: {len(rows)}"
        )
        messagebox.showinfo(
            "Выгрузка завершена",
            f"Тип источника: {normalize_source_type(source_type)}\n"
            f"ID источника: {source_id}\n"
            f"Полей выгружено: {len(rows)}\n"
            f"Файл:\n{output_file}",
        )
        self.selection_dropdown.suppress_next_focus_popup = True
        self.selection_dropdown.hide_popup()
        self.export_button.focus_set()

    def _save_settings(self) -> None:
        try:
            account = validate_account(self.account_var.get())
            token = validate_token(self.token_var.get())
            exports_dir = self.exports_dir_var.get()

            test_config = {
                "account": account,
                "token": token,
                "base_url": f"https://{account}.planfix.ru/rest",
            }

            self.status_var.set("Проверяю аккаунт и токен...")
            self.root.update_idletasks()
            check_connection(test_config)

            save_account(account)
            save_token(account, token)
            save_exports_dir(exports_dir)

            from planfix_export_fields_interactive import load_config

            self.config = load_config()
            self.exports_dir_var.set(str(get_exports_dir()))
            self._on_source_type_changed()
        except Exception as error:
            messagebox.showerror(
                "Не удалось сохранить настройки",
                str(error),
            )
            return

        messagebox.showinfo(
            "Настройки сохранены",
            "Аккаунт, токен и папка выгрузок успешно сохранены.",
        )

    def _choose_exports_dir(self) -> None:
        initial_dir = self.exports_dir_var.get() or str(get_exports_dir())
        selected_dir = filedialog.askdirectory(
            title="Выберите папку для выгрузок",
            initialdir=initial_dir,
        )

        if selected_dir:
            self.exports_dir_var.set(selected_dir)

    def _open_exports_dir(self) -> None:
        try:
            exports_dir = get_exports_dir()
            exports_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(exports_dir)
        except Exception as error:
            messagebox.showerror(
                "Не удалось открыть папку",
                str(error),
            )

    def _open_user_guide(self) -> None:
        webbrowser.open(USER_GUIDE_URL)

    def _show_about(self) -> None:
        about_window = tk.Toplevel(self.root)
        about_window.title("О программе")
        about_window.resizable(False, False)
        about_window.transient(self.root)
        about_window.grab_set()

        frame = tk.Frame(about_window, padx=18, pady=18)
        frame.pack(fill="both", expand=True)

        tk.Label(
            frame,
            text="Planfix Field Exporter",
            font=("Segoe UI", 12, "bold"),
        ).grid(row=0, column=0, sticky="w")

        tk.Label(
            frame,
            text=f"Версия {APP_VERSION}",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        tk.Label(
            frame,
            text="Выгрузка пользовательских полей Planfix в CSV.",
            justify="left",
        ).grid(row=2, column=0, sticky="w", pady=(0, 12))

        link_label = tk.Label(
            frame,
            text=PROJECT_URL,
            fg="#0066cc",
            cursor="hand2",
        )
        link_label.grid(row=3, column=0, sticky="w", pady=(0, 16))
        link_label.bind("<Button-1>", lambda _event: webbrowser.open(PROJECT_URL))

        tk.Button(
            frame,
            text="Закрыть",
            width=12,
            command=about_window.destroy,
        ).grid(row=4, column=0, sticky="e")

    def _bind_entry_shortcuts(self, entry: tk.Entry) -> None:
        entry.bind("<Control-KeyPress>", lambda event: self._handle_control_shortcut(entry, event))

    @staticmethod
    def _handle_virtual_event(entry: tk.Entry, virtual_event: str) -> str:
        entry.event_generate(virtual_event)
        return "break"

    def _handle_control_shortcut(self, entry: tk.Entry, event: tk.Event) -> str | None:
        shortcut_by_keycode = {
            67: "<<Copy>>",
            86: "<<Paste>>",
            88: "<<Cut>>",
        }

        virtual_event = shortcut_by_keycode.get(event.keycode)

        if not virtual_event:
            return None

        return self._handle_virtual_event(entry, virtual_event)

    def show(self) -> None:
        self.root.mainloop()
