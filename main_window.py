import tkinter as tk
from tkinter import messagebox, ttk

from csv_export import save_to_csv
from field_exporter import get_fields_by_source, normalize_field, normalize_source_type
from planfix_client import get_object_list, get_task_template_list
from settings import (
    load_account,
    load_token,
    make_named_output_filename,
    save_account,
    save_token,
)
from version import APP_VERSION


class MainWindow:
    def __init__(self, config: dict) -> None:
        self.config = config

        self.root = tk.Tk()
        self.root.title(f"Planfix Field Exporter {APP_VERSION}")
        self.root.resizable(False, False)

        self.source_type_var = tk.StringVar(value="object")
        self.status_var = tk.StringVar(value="Выберите источник и загрузите список.")
        self.loaded_count_var = tk.StringVar(value="")
        self.account_var = tk.StringVar()
        self.token_var = tk.StringVar()

        self.items_by_display_name: dict[str, dict] = {}

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
            pady=(0, 16),
        )
        tk.Button(
            settings_frame,
            text="Сохранить настройки",
            width=20,
            command=self._save_settings,
        ).grid(row=7, column=0, sticky="e")

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

        self.selection_combo = ttk.Combobox(
            selection_frame,
            state="readonly",
            width=68,
        )
        self.selection_combo.grid(row=1, column=0, sticky="ew")

        action_frame = tk.Frame(work_frame)
        action_frame.grid(row=2, column=0, sticky="ew", pady=(12, 0))

        tk.Button(
            action_frame,
            text="Выгрузить",
            width=14,
            command=self._export_selected_item,
        ).pack(side="right")

        tk.Label(
            work_frame,
            textvariable=self.status_var,
            justify="left",
            fg="#555555",
        ).grid(row=3, column=0, sticky="w", pady=(14, 0))

    def _load_settings(self) -> None:
        account = load_account()

        if not account:
            return

        self.account_var.set(account)

        token = load_token(account)
        if token:
            self.token_var.set(token)

    def _on_source_type_changed(self) -> None:
        self.items_by_display_name.clear()
        self.selection_combo["values"] = []
        self.selection_combo.set("")
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

        sorted_items = sorted(
            items,
            key=lambda item: str(item.get("name", "")).casefold(),
        )

        display_names = []
        self.items_by_display_name.clear()

        for item in sorted_items:
            item_id = item.get("id", "")
            item_name = item.get("name", "")
            display_name = f"{item_name} ({id_label}: {item_id})"
            display_names.append(display_name)
            self.items_by_display_name[display_name] = item

        self.selection_combo["values"] = display_names

        if display_names:
            self.selection_combo.current(0)
            if source_type == "object":
                self.loaded_count_var.set(f"Загружено объектов: {len(display_names)}")
            else:
                self.loaded_count_var.set(f"Загружено шаблонов: {len(display_names)}")
            self.status_var.set("")
        else:
            self.selection_combo.set("")
            self.loaded_count_var.set("")
            self.status_var.set("Список пуст.")

    def _has_ready_config(self) -> bool:
        return bool(
            self.config.get("account")
            and self.config.get("token")
            and self.config.get("base_url")
        )

    def _export_selected_item(self) -> None:
        display_name = self.selection_combo.get()
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

    def _save_settings(self) -> None:
        try:
            account = self.account_var.get()
            token = self.token_var.get()

            save_account(account)
            save_token(account, token)

            from planfix_export_fields_interactive import load_config

            self.config = load_config()
            self._on_source_type_changed()
        except Exception as error:
            messagebox.showerror(
                "Не удалось сохранить настройки",
                str(error),
            )
            return

        messagebox.showinfo(
            "Настройки сохранены",
            "Аккаунт и токен успешно сохранены.",
        )

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
