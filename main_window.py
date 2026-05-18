import os
import tkinter as tk
import webbrowser
from tkinter import filedialog, messagebox, ttk

from app_links import PROJECT_URL, USER_GUIDE_URL
from app_resources import resource_path
from csv_export import CSV_COLUMNS as FIELD_COLUMNS, save_to_csv
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
    validate_exports_dir,
    validate_account,
    validate_token,
)
from version import APP_VERSION


BG = "#f3f6fb"
CARD_BG = "#ffffff"
TEXT = "#172033"
MUTED = "#64748b"
BORDER = "#dbe3ef"
PRIMARY = "#2563eb"
PRIMARY_HOVER = "#1d4ed8"
SOFT_BLUE = "#eaf2ff"

DEFAULT_COLUMNS = [
    "ID поля",
    "Название поля",
    "Тип поля",
]

COLUMN_WIDTHS = {
    "Тип источника": 120,
    "ID источника": 100,
    "Название источника": 180,
    "ID поля": 90,
    "Название поля": 220,
    "Названия поля по языкам": 220,
    "ID типа поля": 100,
    "Тип поля": 180,
    "Формула": 300,
    "Формула в одну строку": 300,
    "ID группы полей": 120,
    "ID справочника": 120,
    "Опции поля": 240,
    "Значения списка": 260,
    "Поля справочника": 260,
    "ID типа результата формулы": 180,
    "Тип результата формулы": 180,
    "Разделитель": 110,
    "Количество знаков после запятой": 220,
    "JSON поля": 420,
    "JSON поля в одну строку": 420,
}


class MainWindow:
    def __init__(self, config: dict) -> None:
        self.config = config

        self.root = tk.Tk()
        self.root.title(f"Planfix Field Exporter {APP_VERSION}")
        try:
            self.root.iconbitmap(resource_path("assets/app-icon.ico"))
        except tk.TclError:
            pass

        self.root.geometry("1180x760")
        self.root.minsize(1040, 660)
        self.root.configure(bg=BG)
        self.root.option_add("*Font", "{Segoe UI} 10")

        self.source_type_var = tk.StringVar(value="object")
        self.status_var = tk.StringVar(value="Выберите источник и загрузите список.")
        self.loaded_count_var = tk.StringVar(value="")
        self.account_var = tk.StringVar()
        self.token_var = tk.StringVar()
        self.exports_dir_var = tk.StringVar()
        self.result_title_var = tk.StringVar(value="Поля не загружены")
        self.result_count_var = tk.StringVar(value="")
        self.selected_columns_count_var = tk.StringVar(value="")

        self.items_by_display_name: dict[str, dict] = {}
        self.all_items: list[dict] = []
        self.current_rows: list[dict] = []
        self.current_source_type: str | None = None
        self.current_source_id: int | None = None
        self.current_source_name = ""
        self.active_cell_row_id: str | None = None
        self.active_cell_column: str | None = None
        self.active_cell_value = ""
        self.active_cell_overlay: tk.Label | None = None
        self.sort_column: str | None = None
        self.sort_reverse = False
        self.column_vars: dict[str, tk.BooleanVar] = {
            column: tk.BooleanVar(value=column in DEFAULT_COLUMNS)
            for column in FIELD_COLUMNS
        }
        self.column_filter_vars: dict[str, tk.StringVar] = {
            column: tk.StringVar(value="")
            for column in FIELD_COLUMNS
        }
        self.rendered_filter_columns: tuple[str, ...] | None = None

        self._configure_styles()
        self._build_ui()
        for filter_var in self.column_filter_vars.values():
            filter_var.trace_add("write", lambda *_args: self._refresh_result_table())
        self._load_settings()
        self._update_source_label()
        self._sync_source_buttons()

        if self._has_ready_config():
            self._load_items()
        else:
            self.status_var.set("Введите аккаунт и токен, затем нажмите «Сохранить».")

    def _configure_styles(self) -> None:
        self.style = ttk.Style(self.root)
        if "clam" in self.style.theme_names():
            self.style.theme_use("clam")

        self.style.configure(".", font=("Segoe UI", 10))
        self.style.configure("App.TFrame", background=BG)
        self.style.configure("Card.TFrame", background=CARD_BG)
        self.style.configure("Title.TLabel", background=BG, foreground=TEXT, font=("Segoe UI", 20, "bold"))
        self.style.configure("Subtitle.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 10))
        self.style.configure("CardTitle.TLabel", background=CARD_BG, foreground=TEXT, font=("Segoe UI", 12, "bold"))
        self.style.configure("CardText.TLabel", background=CARD_BG, foreground=TEXT)
        self.style.configure("Muted.TLabel", background=CARD_BG, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("Status.TLabel", background=BG, foreground=MUTED, font=("Segoe UI", 9))
        self.style.configure("Badge.TLabel", background=SOFT_BLUE, foreground=PRIMARY, font=("Segoe UI", 9, "bold"), padding=(10, 5))
        self.style.configure("Link.TLabel", background=BG, foreground=PRIMARY, font=("Segoe UI", 9))
        self.style.configure("CardLink.TLabel", background=CARD_BG, foreground=PRIMARY, font=("Segoe UI", 9))
        self.style.configure("App.TEntry", fieldbackground="#ffffff", foreground=TEXT, bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=(10, 8))
        self.style.configure("Primary.TButton", background=PRIMARY, foreground="#ffffff", borderwidth=0, focusthickness=0, padding=(16, 10), font=("Segoe UI", 10, "bold"))
        self.style.map("Primary.TButton", background=[("active", PRIMARY_HOVER), ("pressed", PRIMARY_HOVER)], foreground=[("disabled", "#dbeafe")])
        self.style.configure("Secondary.TButton", background="#eef3f9", foreground=TEXT, borderwidth=0, focusthickness=0, padding=(12, 9))
        self.style.map("Secondary.TButton", background=[("active", "#e2eaf5"), ("pressed", "#d7e2ef")])
        self.style.configure("Segmented.TButton", background="#eef3f9", foreground=TEXT, borderwidth=0, focusthickness=0, padding=(14, 9))
        self.style.map("Segmented.TButton", background=[("active", "#e2eaf5")])
        self.style.configure("SegmentedActive.TButton", background=PRIMARY, foreground="#ffffff", borderwidth=0, focusthickness=0, padding=(14, 9), font=("Segoe UI", 10, "bold"))
        self.style.map("SegmentedActive.TButton", background=[("active", PRIMARY_HOVER), ("pressed", PRIMARY_HOVER)])
        self.style.configure("Column.TCheckbutton", background=CARD_BG, foreground=TEXT)
        self.style.map("Column.TCheckbutton", background=[("active", CARD_BG)])
        self.style.configure("Results.Treeview", background="#ffffff", fieldbackground="#ffffff", foreground=TEXT, rowheight=28, borderwidth=0)
        self.style.configure("Results.Treeview.Heading", font=("Segoe UI", 9, "bold"), foreground=TEXT)

    def _build_ui(self) -> None:
        frame = tk.Frame(self.root, bg=BG, padx=24, pady=22)
        frame.pack(fill="both", expand=True)
        frame.grid_columnconfigure(1, weight=1)
        frame.grid_rowconfigure(1, weight=1)

        header = tk.Frame(frame, bg=BG)
        header.grid(row=0, column=0, columnspan=2, sticky="ew", pady=(0, 18))
        header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            header,
            text="Planfix Field Exporter",
            style="Title.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header,
            text="Просмотр пользовательских полей Planfix в интерфейсе приложения",
            style="Subtitle.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(3, 0))
        ttk.Label(
            header,
            text=f"v{APP_VERSION}",
            style="Badge.TLabel",
        ).grid(row=0, column=1, rowspan=2, sticky="e")

        left_frame = tk.Frame(frame, bg=BG)
        left_frame.grid(row=1, column=0, sticky="nsew", padx=(0, 18))
        left_frame.grid_columnconfigure(0, weight=1)
        left_frame.grid_rowconfigure(1, weight=1)

        settings_frame = self._create_card(left_frame)
        settings_frame.grid(row=0, column=0, sticky="ew")
        settings_frame.grid_columnconfigure(0, weight=1)

        self._section_header(
            settings_frame,
            0,
            "Подключение",
            "Данные сохраняются локально, токен хранится в системном хранилище Windows.",
        )

        self._field_label(settings_frame, 2, "Аккаунт Planfix")
        account_entry = ttk.Entry(
            settings_frame,
            textvariable=self.account_var,
            width=34,
            style="App.TEntry",
        )
        account_entry.grid(row=3, column=0, sticky="ew")
        self._hint(settings_frame, 4, "Например: engineering  (без .planfix.ru)")

        self._field_label(settings_frame, 5, "Токен доступа", top=14)
        token_entry = ttk.Entry(
            settings_frame,
            textvariable=self.token_var,
            width=34,
            show="*",
            style="App.TEntry",
        )
        token_entry.grid(row=6, column=0, sticky="ew")
        self._hint(settings_frame, 7, "Вставьте только сам токен, без слова Bearer.")

        self._field_label(settings_frame, 8, "Папка выгрузок", top=14)
        exports_frame = tk.Frame(settings_frame, bg=CARD_BG)
        exports_frame.grid(row=9, column=0, sticky="ew")
        exports_frame.grid_columnconfigure(0, weight=1)

        exports_entry = ttk.Entry(
            exports_frame,
            textvariable=self.exports_dir_var,
            width=24,
            style="App.TEntry",
        )
        exports_entry.grid(row=0, column=0, sticky="ew")

        ttk.Button(
            exports_frame,
            text="Выбрать",
            command=self._choose_exports_dir,
            style="Secondary.TButton",
        ).grid(row=0, column=1, padx=(8, 0))

        ttk.Button(
            exports_frame,
            text="Открыть",
            command=self._open_exports_dir,
            style="Secondary.TButton",
        ).grid(row=0, column=2, padx=(8, 0))

        ttk.Button(
            settings_frame,
            text="Сохранить настройки",
            command=self._save_settings,
            style="Primary.TButton",
        ).grid(row=10, column=0, sticky="ew", pady=(18, 0))

        self._bind_entry_shortcuts(account_entry)
        self._bind_entry_shortcuts(token_entry)
        self._bind_entry_shortcuts(exports_entry)

        columns_frame = self._create_card(left_frame)
        columns_frame.grid(row=1, column=0, sticky="nsew", pady=(18, 0))
        columns_frame.grid_columnconfigure(0, weight=1)
        columns_frame.grid_rowconfigure(3, weight=1)

        self._section_header(
            columns_frame,
            0,
            "Столбцы",
            "Отметьте поля, которые должны быть видны в таблице.",
        )

        column_actions = tk.Frame(columns_frame, bg=CARD_BG)
        column_actions.grid(row=2, column=0, sticky="ew", pady=(0, 10))
        column_actions.grid_columnconfigure(0, weight=1)
        column_actions.grid_columnconfigure(1, weight=1)
        column_actions.grid_columnconfigure(2, weight=1)

        ttk.Button(
            column_actions,
            text="Основные",
            command=self._select_default_columns,
            style="Secondary.TButton",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 6))
        ttk.Button(
            column_actions,
            text="Все",
            command=lambda: self._set_all_columns(True),
            style="Secondary.TButton",
        ).grid(row=0, column=1, sticky="ew", padx=6)
        ttk.Button(
            column_actions,
            text="Снять",
            command=lambda: self._set_all_columns(False),
            style="Secondary.TButton",
        ).grid(row=0, column=2, sticky="ew", padx=(6, 0))

        self._build_columns_list(columns_frame, row=3)
        ttk.Label(
            columns_frame,
            textvariable=self.selected_columns_count_var,
            style="Muted.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(10, 0))
        self._update_selected_columns_count()

        work_frame = tk.Frame(frame, bg=BG)
        work_frame.grid(row=1, column=1, sticky="nsew")
        work_frame.grid_columnconfigure(0, weight=1)
        work_frame.grid_rowconfigure(2, weight=1)

        source_frame = self._create_card(work_frame)
        source_frame.grid(row=0, column=0, sticky="ew")
        source_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(
            source_frame,
            text="Источник",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w", padx=(0, 14))

        source_buttons = tk.Frame(source_frame, bg=CARD_BG)
        source_buttons.grid(row=0, column=1, sticky="ew")
        source_buttons.grid_columnconfigure(0, weight=1)
        source_buttons.grid_columnconfigure(1, weight=1)

        self.object_source_button = ttk.Button(
            source_buttons,
            text="Поля объекта",
            command=lambda: self._set_source_type("object"),
            style="SegmentedActive.TButton",
        )
        self.object_source_button.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.template_source_button = ttk.Button(
            source_buttons,
            text="Поля шаблона задачи",
            command=lambda: self._set_source_type("task_template"),
            style="Segmented.TButton",
        )
        self.template_source_button.grid(row=0, column=1, sticky="ew", padx=(6, 0))

        selection_frame = self._create_card(work_frame)
        selection_frame.grid(row=1, column=0, sticky="ew", pady=(18, 0))
        selection_frame.grid_columnconfigure(0, weight=1)
        self._section_header(
            selection_frame,
            0,
            "Выбор источника",
            "Начните вводить название или ID, чтобы отфильтровать список.",
        )

        meta_frame = tk.Frame(selection_frame, bg=CARD_BG)
        meta_frame.grid(row=2, column=0, sticky="ew", pady=(4, 8))
        meta_frame.grid_columnconfigure(1, weight=1)

        self.selection_label = ttk.Label(meta_frame, text="", style="CardText.TLabel")
        self.selection_label.grid(row=0, column=0, sticky="w")

        ttk.Label(
            meta_frame,
            textvariable=self.loaded_count_var,
            justify="right",
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="e")

        self.selection_dropdown = SearchableDropdown(
            selection_frame,
            width=68,
            style="Card.TFrame",
        )
        self.selection_dropdown.grid(row=3, column=0, sticky="ew")
        self.selection_dropdown.bind_on_select(self._on_source_selected)

        ttk.Label(
            selection_frame,
            text="При выборе источника поля загрузятся автоматически.",
            style="Muted.TLabel",
        ).grid(row=4, column=0, sticky="w", pady=(14, 0))

        results_frame = self._create_card(work_frame)
        results_frame.grid(row=2, column=0, sticky="nsew", pady=(18, 0))
        results_frame.grid_columnconfigure(0, weight=1)
        results_frame.grid_rowconfigure(1, weight=1)

        results_header = tk.Frame(results_frame, bg=CARD_BG)
        results_header.grid(row=0, column=0, sticky="ew")
        results_header.grid_columnconfigure(0, weight=1)

        ttk.Label(
            results_header,
            textvariable=self.result_title_var,
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            results_header,
            textvariable=self.result_count_var,
            justify="right",
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(0, 10))

        ttk.Button(
            results_header,
            text="Экспорт CSV",
            command=self._export_current_table_to_csv,
            style="Primary.TButton",
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))

        ttk.Button(
            results_header,
            text="Сбросить фильтры",
            command=self._clear_table_filter,
            style="Secondary.TButton",
        ).grid(row=0, column=3, sticky="e")

        table_frame = tk.Frame(results_frame, bg=CARD_BG)
        table_frame.grid(row=1, column=0, sticky="nsew", pady=(12, 0))
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(1, weight=1)

        self.column_filter_canvas = tk.Canvas(
            table_frame,
            background="#f8fafc",
            borderwidth=0,
            height=72,
            highlightbackground=BORDER,
            highlightthickness=1,
            xscrollincrement=8,
        )
        self.column_filter_canvas.grid(row=0, column=0, sticky="ew")
        self.column_filter_frame = tk.Frame(self.column_filter_canvas, bg="#f8fafc")
        self.column_filter_window = self.column_filter_canvas.create_window(
            (0, 0),
            window=self.column_filter_frame,
            anchor="nw",
        )

        self.result_table = ttk.Treeview(
            table_frame,
            show="",
            style="Results.Treeview",
        )
        self.result_table.grid(row=1, column=0, sticky="nsew")
        self.result_table_context_menu = tk.Menu(self.root, tearoff=0)
        self.result_table_context_menu.add_command(
            label="Копировать значение",
            command=self._copy_active_cell_value,
        )
        self.result_table_context_menu.add_command(
            label="Фильтровать по значению",
            command=self._filter_by_active_cell_value,
        )

        self.table_vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=self._on_table_yscroll,
        )
        self.table_vertical_scrollbar.grid(row=1, column=1, sticky="ns")

        self.table_horizontal_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=self._on_table_xscroll,
        )
        self.table_horizontal_scrollbar.grid(row=2, column=0, sticky="ew")

        self.result_table.configure(
            yscrollcommand=self._on_table_yview_changed,
            xscrollcommand=self._on_table_xview_changed,
        )
        self.result_table.bind("<Control-KeyPress>", self._handle_table_control_shortcut)
        self.result_table.bind("<Button-1>", self._handle_table_left_click)
        self.result_table.bind("<Button-3>", self._handle_table_right_click)
        self._refresh_result_table()

        footer_frame = tk.Frame(frame, bg=BG)
        footer_frame.grid(row=2, column=0, columnspan=2, sticky="ew", pady=(18, 0))
        footer_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(
            footer_frame,
            textvariable=self.status_var,
            style="Status.TLabel",
        ).grid(row=0, column=0, sticky="w")

        links_frame = tk.Frame(footer_frame, bg=BG)
        links_frame.grid(row=0, column=2, sticky="e")

        guide_link = ttk.Label(
            links_frame,
            text="Руководство",
            cursor="hand2",
            style="Link.TLabel",
        )
        guide_link.pack(side="left")
        guide_link.bind("<Button-1>", lambda _event: self._open_user_guide())

        about_link = ttk.Label(
            links_frame,
            text="О программе",
            cursor="hand2",
            style="Link.TLabel",
        )
        about_link.pack(side="left", padx=(18, 0))
        about_link.bind("<Button-1>", lambda _event: self._show_about())

    def _create_card(self, parent: tk.Misc) -> tk.Frame:
        return tk.Frame(
            parent,
            bg=CARD_BG,
            highlightbackground=BORDER,
            highlightcolor=BORDER,
            highlightthickness=1,
            padx=20,
            pady=18,
        )

    def _section_header(self, parent: tk.Misc, row: int, title: str, subtitle: str) -> None:
        ttk.Label(parent, text=title, style="CardTitle.TLabel").grid(row=row, column=0, sticky="w")
        ttk.Label(
            parent,
            text=subtitle,
            wraplength=340,
            justify="left",
            style="Muted.TLabel",
        ).grid(row=row + 1, column=0, sticky="w", pady=(4, 16))

    def _field_label(self, parent: tk.Misc, row: int, text: str, top: int = 0) -> None:
        ttk.Label(parent, text=text, style="CardText.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            pady=(top, 6),
        )

    def _hint(self, parent: tk.Misc, row: int, text: str) -> None:
        ttk.Label(parent, text=text, style="Muted.TLabel").grid(
            row=row,
            column=0,
            sticky="w",
            pady=(6, 0),
        )

    def _build_columns_list(self, parent: tk.Misc, row: int) -> None:
        scroll_area = tk.Frame(parent, bg=CARD_BG, highlightbackground=BORDER, highlightthickness=1)
        scroll_area.grid(row=row, column=0, sticky="nsew")
        scroll_area.grid_columnconfigure(0, weight=1)
        scroll_area.grid_rowconfigure(0, weight=1)

        canvas = tk.Canvas(
            scroll_area,
            background=CARD_BG,
            borderwidth=0,
            highlightthickness=0,
            height=230,
        )
        scrollbar = ttk.Scrollbar(scroll_area, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=scrollbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        scrollbar.grid(row=0, column=1, sticky="ns")

        columns_inner = tk.Frame(canvas, bg=CARD_BG)
        inner_window = canvas.create_window((0, 0), window=columns_inner, anchor="nw")

        def update_scroll_region(_event=None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))

        def update_inner_width(event) -> None:
            canvas.itemconfigure(inner_window, width=event.width)

        columns_inner.bind("<Configure>", update_scroll_region)
        canvas.bind("<Configure>", update_inner_width)

        for index, column in enumerate(FIELD_COLUMNS):
            checkbox = ttk.Checkbutton(
                columns_inner,
                text=column,
                variable=self.column_vars[column],
                command=self._on_columns_changed,
                style="Column.TCheckbutton",
            )
            checkbox.grid(row=index, column=0, sticky="w", padx=10, pady=4)

    def _selected_columns(self) -> list[str]:
        return [
            column
            for column in FIELD_COLUMNS
            if self.column_vars[column].get()
        ]

    def _set_all_columns(self, selected: bool) -> None:
        for variable in self.column_vars.values():
            variable.set(selected)

        self._on_columns_changed()

    def _select_default_columns(self) -> None:
        for column, variable in self.column_vars.items():
            variable.set(column in DEFAULT_COLUMNS)

        self._on_columns_changed()

    def _on_columns_changed(self) -> None:
        self._update_selected_columns_count()
        self._refresh_result_table()

    def _update_selected_columns_count(self) -> None:
        selected_count = len(self._selected_columns())
        self.selected_columns_count_var.set(
            f"Выбрано столбцов: {selected_count} из {len(FIELD_COLUMNS)}"
        )

    def _format_table_value(self, value) -> str:
        if value is None:
            return ""

        return " ".join(str(value).replace("\r", "\n").split())

    def _sync_table_state(self, selected_columns: list[str]) -> None:
        if self.sort_column is not None and self.sort_column not in selected_columns:
            self.sort_column = None
            self.sort_reverse = False
            self.rendered_filter_columns = None

    def _clear_table_filter(self) -> None:
        for filter_var in self.column_filter_vars.values():
            filter_var.set("")

    def _refresh_column_filter_row(self, selected_columns: list[str]) -> None:
        if not hasattr(self, "column_filter_frame"):
            return

        filter_columns = tuple(selected_columns)

        if self.rendered_filter_columns == filter_columns:
            return

        self.rendered_filter_columns = filter_columns

        for child in self.column_filter_frame.winfo_children():
            child.destroy()

        for index in range(len(FIELD_COLUMNS)):
            self.column_filter_frame.grid_columnconfigure(index, minsize=0)

        for index, column in enumerate(selected_columns):
            width = COLUMN_WIDTHS.get(column, 160)
            self.column_filter_frame.grid_columnconfigure(index, minsize=width)

            filter_cell = tk.Frame(
                self.column_filter_frame,
                width=width,
                height=70,
                bg="#f8fafc",
                highlightbackground=BORDER,
                highlightthickness=1,
            )
            filter_cell.grid(row=0, column=index, sticky="nsew")
            filter_cell.grid_propagate(False)

            header_label = tk.Label(
                filter_cell,
                text=self._heading_text(column),
                anchor="w",
                bg="#eef3f9",
                fg=TEXT,
                cursor="hand2",
                font=("Segoe UI", 9, "bold"),
                padx=6,
                pady=3,
            )
            header_label.pack(fill="x")
            header_label.bind(
                "<Button-1>",
                lambda _event, selected_column=column: self._sort_by_column(selected_column),
            )

            filter_row = tk.Frame(filter_cell, bg="#f8fafc")
            filter_row.pack(fill="x", padx=4, pady=(5, 0))

            filter_entry = ttk.Entry(
                filter_row,
                textvariable=self.column_filter_vars[column],
                width=1,
                style="App.TEntry",
            )
            filter_entry.pack(side="left", fill="x", expand=True)
            self._bind_entry_shortcuts(filter_entry)

            filter_icon = self._create_filter_icon(filter_row)
            filter_icon.pack(side="left", padx=(4, 0))

        self.column_filter_frame.update_idletasks()
        self.column_filter_canvas.configure(scrollregion=self.column_filter_canvas.bbox("all"))

    def _create_filter_icon(self, parent: tk.Misc) -> tk.Canvas:
        icon = tk.Canvas(
            parent,
            width=14,
            height=18,
            background="#f8fafc",
            borderwidth=0,
            highlightthickness=0,
        )
        icon.create_polygon(
            2,
            4,
            12,
            4,
            8,
            9,
            8,
            14,
            6,
            15,
            6,
            9,
            fill=MUTED,
            outline=MUTED,
        )
        return icon

    def _on_table_xscroll(self, *args) -> None:
        self.result_table.xview(*args)

        if hasattr(self, "column_filter_canvas"):
            self.column_filter_canvas.xview(*args)

        self._place_active_cell_overlay()

    def _on_table_yscroll(self, *args) -> None:
        self.result_table.yview(*args)
        self._place_active_cell_overlay()

    def _on_table_xview_changed(self, first: str, last: str) -> None:
        if hasattr(self, "table_horizontal_scrollbar"):
            self.table_horizontal_scrollbar.set(first, last)

        if hasattr(self, "column_filter_canvas"):
            self.column_filter_canvas.xview_moveto(first)

        self._place_active_cell_overlay()

    def _on_table_yview_changed(self, first: str, last: str) -> None:
        if hasattr(self, "table_vertical_scrollbar"):
            self.table_vertical_scrollbar.set(first, last)

        self._place_active_cell_overlay()

    def _table_column_from_identifier(self, column_identifier: str) -> str | None:
        if not column_identifier.startswith("#"):
            return None

        try:
            column_index = int(column_identifier[1:]) - 1
        except ValueError:
            return None

        columns = list(self.result_table["columns"])

        if column_index < 0 or column_index >= len(columns):
            return None

        return columns[column_index]

    def _cell_value(self, row_id: str, column: str) -> str:
        columns = list(self.result_table["columns"])

        if column not in columns:
            return ""

        values = self.result_table.item(row_id, "values")
        column_index = columns.index(column)

        if column_index >= len(values):
            return ""

        return str(values[column_index])

    def _set_active_cell(self, row_id: str, column: str) -> None:
        self.active_cell_row_id = row_id
        self.active_cell_column = column
        self.active_cell_value = self._cell_value(row_id, column)
        self.result_table.selection_set(row_id)
        self.result_table.focus(row_id)
        self.result_table.focus_set()
        self._place_active_cell_overlay()

    def _clear_active_cell(self) -> None:
        self.active_cell_row_id = None
        self.active_cell_column = None
        self.active_cell_value = ""

        if self.active_cell_overlay is not None:
            self.active_cell_overlay.destroy()
            self.active_cell_overlay = None

    def _place_active_cell_overlay(self) -> None:
        if (
            self.active_cell_row_id is None
            or self.active_cell_column is None
            or not self.result_table.exists(self.active_cell_row_id)
        ):
            if self.active_cell_overlay is not None:
                self.active_cell_overlay.place_forget()
            return

        bbox = self.result_table.bbox(self.active_cell_row_id, self.active_cell_column)

        if not bbox:
            if self.active_cell_overlay is not None:
                self.active_cell_overlay.place_forget()
            return

        if self.active_cell_overlay is None:
            self.active_cell_overlay = tk.Label(
                self.result_table,
                anchor="w",
                background=PRIMARY,
                foreground="#ffffff",
                font=("Segoe UI", 10),
                padx=4,
            )
            self.active_cell_overlay.bind(
                "<Button-1>",
                lambda _event: self.result_table.focus_set(),
            )
            self.active_cell_overlay.bind(
                "<Button-3>",
                lambda event: self._show_active_cell_context_menu(event),
            )

        x, y, width, height = bbox
        self.active_cell_overlay.configure(text=self.active_cell_value)
        self.active_cell_overlay.place(x=x, y=y, width=width, height=height)
        self.active_cell_overlay.lift()

    def _handle_table_left_click(self, event: tk.Event) -> None:
        row_id = self.result_table.identify_row(event.y)
        column = self._table_column_from_identifier(self.result_table.identify_column(event.x))

        if not row_id or column is None:
            self._clear_active_cell()
            return

        self._set_active_cell(row_id, column)

    def _handle_table_right_click(self, event: tk.Event) -> str:
        row_id = self.result_table.identify_row(event.y)
        column = self._table_column_from_identifier(self.result_table.identify_column(event.x))

        if not row_id or column is None:
            self._clear_active_cell()
            return "break"

        self._set_active_cell(row_id, column)
        self._show_active_cell_context_menu(event)
        return "break"

    def _show_active_cell_context_menu(self, event: tk.Event) -> str:
        try:
            self.result_table_context_menu.tk_popup(event.x_root, event.y_root)
        finally:
            self.result_table_context_menu.grab_release()

        return "break"

    def _row_matches_filter(self, row: dict, selected_columns: list[str]) -> bool:
        active_filters = [
            (column, self.column_filter_vars[column].get().strip().casefold())
            for column in selected_columns
            if self.column_filter_vars[column].get().strip()
        ]

        return all(
            filter_text in self._format_table_value(row.get(column, "")).casefold()
            for column, filter_text in active_filters
        )

    def _sort_key(self, row: dict):
        if self.sort_column is None:
            return ""

        value = row.get(self.sort_column, "")

        if isinstance(value, (int, float)):
            return (0, value)

        text_value = self._format_table_value(value)
        normalized_number = text_value.replace(",", ".")

        try:
            return (0, float(normalized_number))
        except ValueError:
            return (1, text_value.casefold())

    def _sort_rows(self, rows: list[dict]) -> list[dict]:
        if self.sort_column is None:
            return rows

        return sorted(rows, key=self._sort_key, reverse=self.sort_reverse)

    def _sort_by_column(self, column: str) -> None:
        if self.sort_column == column:
            self.sort_reverse = not self.sort_reverse
        else:
            self.sort_column = column
            self.sort_reverse = False

        self.rendered_filter_columns = None
        self._refresh_result_table()

    def _heading_text(self, column: str) -> str:
        if self.sort_column != column:
            return f"↕ {column}"

        direction = "▼" if self.sort_reverse else "▲"
        return f"{column} {direction}"

    def _refresh_result_table(self) -> None:
        if not hasattr(self, "result_table"):
            return

        self._clear_active_cell()
        selected_columns = self._selected_columns()
        self._sync_table_state(selected_columns)
        self._refresh_column_filter_row(selected_columns)
        self.result_table.delete(*self.result_table.get_children())
        self.result_table.configure(columns=selected_columns)

        for column in selected_columns:
            width = COLUMN_WIDTHS.get(column, 160)
            self.result_table.heading(
                column,
                text=self._heading_text(column),
                command=lambda selected_column=column: self._sort_by_column(selected_column),
            )
            self.result_table.column(
                column,
                width=width,
                minwidth=80,
                stretch=False,
                anchor="w",
            )

        visible_rows = [
            row
            for row in self.current_rows
            if self._row_matches_filter(row, selected_columns)
        ]
        visible_rows = self._sort_rows(visible_rows)

        for row in visible_rows:
            values = [
                self._format_table_value(row.get(column, ""))
                for column in selected_columns
            ]
            self.result_table.insert("", tk.END, values=values)

        if self.current_rows:
            self.result_count_var.set(
                f"Показано: {len(visible_rows)} из {len(self.current_rows)}"
            )

        if not selected_columns:
            self.status_var.set("Выберите хотя бы один столбец для отображения.")

    def _handle_table_control_shortcut(self, event: tk.Event) -> str | None:
        shortcut_by_keycode = {
            65: self._select_active_cell_value,
            67: self._copy_active_cell_value,
        }

        handler = shortcut_by_keycode.get(event.keycode)

        if handler is None:
            return None

        handler()
        return "break"

    def _ensure_active_cell(self) -> bool:
        if (
            self.active_cell_row_id is not None
            and self.active_cell_column is not None
            and self.result_table.exists(self.active_cell_row_id)
        ):
            return True

        row_id = self.result_table.focus()

        if not row_id:
            row_ids = self.result_table.get_children()
            row_id = row_ids[0] if row_ids else ""

        columns = list(self.result_table["columns"])

        if not row_id or not columns:
            return False

        self._set_active_cell(row_id, columns[0])
        return True

    def _select_active_cell_value(self) -> None:
        if not self._ensure_active_cell():
            return

        self._place_active_cell_overlay()
        self.status_var.set("Выбрано значение таблицы.")

    def _copy_active_cell_value(self) -> None:
        if not self._ensure_active_cell():
            return

        self.root.clipboard_clear()
        self.root.clipboard_append(self.active_cell_value)
        self.status_var.set("Значение скопировано.")

    def _filter_by_active_cell_value(self) -> None:
        if not self._ensure_active_cell() or self.active_cell_column is None:
            return

        self.column_filter_vars[self.active_cell_column].set(self.active_cell_value)
        self.status_var.set("Фильтр применён по выбранному значению.")

    def _load_settings(self) -> None:
        self.exports_dir_var.set(str(get_exports_dir()))

        account = load_account()

        if not account:
            return

        self.account_var.set(account)

        token = load_token(account)
        if token:
            self.token_var.set(token)

    def _set_source_type(self, source_type: str) -> None:
        if self.source_type_var.get() == source_type:
            return

        self.source_type_var.set(source_type)
        self._on_source_type_changed()

    def _sync_source_buttons(self) -> None:
        object_style = "SegmentedActive.TButton" if self.source_type_var.get() == "object" else "Segmented.TButton"
        template_style = "SegmentedActive.TButton" if self.source_type_var.get() == "task_template" else "Segmented.TButton"
        self.object_source_button.configure(style=object_style)
        self.template_source_button.configure(style=template_style)

    def _on_source_type_changed(self) -> None:
        self._sync_source_buttons()
        self.items_by_display_name.clear()
        self.all_items = []
        self.current_rows = []
        self.current_source_type = None
        self.current_source_id = None
        self.current_source_name = ""
        self.sort_column = None
        self.sort_reverse = False
        self._clear_table_filter()
        self.result_title_var.set("Поля не загружены")
        self.result_count_var.set("")
        self._refresh_result_table()
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
            else:
                items = get_task_template_list(self.config)
        except Exception as error:
            self.status_var.set("Не удалось загрузить список.")
            messagebox.showerror("Ошибка", str(error), parent=self.root)
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
            self.status_var.set("Список загружен. Выберите источник для просмотра.")
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

    def _on_source_selected(self, _display_name: str) -> None:
        self._show_selected_item_fields()

    def _show_selected_item_fields(self) -> None:
        display_name = self.selection_dropdown.get()
        selected_item = self.items_by_display_name.get(display_name)

        if not selected_item:
            messagebox.showwarning(
                "Ничего не выбрано",
                "Сначала загрузите список и выберите нужную запись.",
                parent=self.root,
            )
            return

        source_type = self.source_type_var.get()
        source_id = int(selected_item["id"])
        source_name = selected_item.get("name", "")

        try:
            self.status_var.set("Загружаю поля...")
            self.root.update_idletasks()

            fields = get_fields_by_source(self.config, source_type, source_id)
            rows = [
                normalize_field(source_type, source_id, source_name, field)
                for field in fields
            ]
        except Exception as error:
            self.status_var.set("Не удалось загрузить поля.")
            messagebox.showerror("Ошибка", str(error), parent=self.root)
            return

        self.current_rows = rows
        self.current_source_type = source_type
        self.current_source_id = source_id
        self.current_source_name = source_name
        display_source_name = source_name if len(source_name) <= 80 else f"{source_name[:77]}..."
        self.result_title_var.set(
            f"{display_source_name} ({normalize_source_type(source_type)} {source_id})"
        )
        self._refresh_result_table()
        if not rows:
            self.result_count_var.set("Показано: 0 из 0")

        if self._selected_columns():
            self.status_var.set(f"Готово. Загружено полей: {len(rows)}")
        else:
            self.status_var.set("Поля загружены. Выберите хотя бы один столбец для отображения.")

        self.selection_dropdown.suppress_next_focus_popup = True
        self.selection_dropdown.hide_popup()
        self.result_table.focus_set()

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
                parent=self.root,
            )
            return

        messagebox.showinfo(
            "Настройки сохранены",
            "Аккаунт, токен и папка выгрузок успешно сохранены.",
            parent=self.root,
        )

    def _choose_exports_dir(self) -> None:
        initial_dir = self.exports_dir_var.get() or str(get_exports_dir())
        selected_dir = filedialog.askdirectory(
            title="Выберите папку для выгрузок",
            initialdir=initial_dir,
            parent=self.root,
        )

        if selected_dir:
            self.exports_dir_var.set(selected_dir)

    def _open_exports_dir(self) -> None:
        try:
            exports_dir = validate_exports_dir(self.exports_dir_var.get() or get_exports_dir())
            exports_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(exports_dir)
        except Exception as error:
            messagebox.showerror(
                "Не удалось открыть папку",
                str(error),
                parent=self.root,
            )

    def _export_current_table_to_csv(self) -> None:
        selected_columns = self._selected_columns()

        if self.current_source_type is None or self.current_source_id is None:
            messagebox.showwarning(
                "Нет данных для выгрузки",
                "Сначала выберите объект или шаблон, чтобы загрузить поля.",
                parent=self.root,
            )
            return

        if not selected_columns:
            messagebox.showwarning(
                "Столбцы не выбраны",
                "Выберите хотя бы один столбец для CSV.",
                parent=self.root,
            )
            return

        try:
            save_exports_dir(self.exports_dir_var.get())
            output_file = make_named_output_filename(
                self.current_source_type,
                self.current_source_id,
                self.current_source_name,
            )
            save_to_csv(self.current_rows, output_file, selected_columns)
            self.exports_dir_var.set(str(get_exports_dir()))
        except Exception as error:
            self.status_var.set("Не удалось сохранить CSV.")
            messagebox.showerror("Ошибка", str(error), parent=self.root)
            return

        self.status_var.set(f"CSV сохранён: {output_file}")
        messagebox.showinfo(
            "CSV сохранён",
            f"Строк: {len(self.current_rows)}\n"
            f"Столбцов: {len(selected_columns)}\n"
            f"Файл:\n{output_file}",
            parent=self.root,
        )

    def _open_user_guide(self) -> None:
        webbrowser.open(USER_GUIDE_URL)

    def _show_about(self) -> None:
        about_window = tk.Toplevel(self.root)
        about_window.title("О программе")
        about_window.resizable(False, False)
        about_window.transient(self.root)
        about_window.grab_set()
        about_window.configure(bg=BG)

        frame = self._create_card(about_window)
        frame.pack(fill="both", expand=True, padx=18, pady=18)

        ttk.Label(
            frame,
            text="Planfix Field Exporter",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")

        ttk.Label(
            frame,
            text=f"Версия {APP_VERSION}",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 12))

        ttk.Label(
            frame,
            text="Просмотр пользовательских полей Planfix в интерфейсе приложения.",
            justify="left",
            style="CardText.TLabel",
        ).grid(row=2, column=0, sticky="w", pady=(0, 12))

        link_label = ttk.Label(
            frame,
            text=PROJECT_URL,
            cursor="hand2",
            style="CardLink.TLabel",
        )
        link_label.grid(row=3, column=0, sticky="w", pady=(0, 16))
        link_label.bind("<Button-1>", lambda _event: webbrowser.open(PROJECT_URL))

        ttk.Button(
            frame,
            text="Закрыть",
            command=about_window.destroy,
            style="Secondary.TButton",
        ).grid(row=4, column=0, sticky="e")

    def _bind_entry_shortcuts(self, entry: tk.Widget) -> None:
        entry.bind("<Control-KeyPress>", lambda event: self._handle_control_shortcut(entry, event))

    @staticmethod
    def _handle_virtual_event(entry: tk.Widget, virtual_event: str) -> str:
        entry.event_generate(virtual_event)
        return "break"

    def _handle_control_shortcut(self, entry: tk.Widget, event: tk.Event) -> str | None:
        if event.keycode == 65:
            try:
                entry.selection_range(0, tk.END)
                entry.icursor(tk.END)
                return "break"
            except tk.TclError:
                return None

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
