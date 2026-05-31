import json
import os
import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

from app_links import PROJECT_URL, USER_GUIDE_URL
from app_resources import resource_path
from csv_export import CSV_COLUMNS as FIELD_COLUMNS, save_to_csv
from field_exporter import get_fields_by_source, normalize_field, normalize_source_type
from formula_search import (
    FormulaSearchCancelled,
    FormulaSearchError,
    FormulaSearchProgress,
    FormulaSearchStopped,
    FormulaUsage,
    RateLimitedPlanfixClient,
    load_directories,
    search_formula_usages,
    usage_to_output_row,
)
from formula_index import (
    FormulaIndexError,
    FormulaIndexStopped,
    build_formula_index,
    load_formula_index,
    load_formula_index_status,
    search_formula_index,
)
from planfix_client import check_connection, get_object_list, get_task_template_list
from searchable_dropdown import SearchableDropdown
from settings import (
    get_exports_dir,
    load_excluded_formula_search_directory_ids,
    load_account,
    load_token,
    make_named_output_filename,
    save_account,
    save_excluded_formula_search_directory_ids,
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
        self.formula_index_status_var = tk.StringVar(value="Индекс формул: не создан")
        self.selected_columns_count_var = tk.StringVar(value="")

        self.items_by_display_name: dict[str, dict] = {}
        self.all_items: list[dict] = []
        self.current_rows: list[dict] = []
        self.current_source_type: str | None = None
        self.current_source_id: int | None = None
        self.current_source_name = ""
        self.rendered_rows_by_item_id: dict[str, dict] = {}
        self.column_widths = dict(COLUMN_WIDTHS)
        self.column_filter_cells: dict[str, tk.Frame] = {}
        self.column_resize_state: dict | None = None
        self.active_cell_row_id: str | None = None
        self.active_cell_column: str | None = None
        self.active_cell_value = ""
        self.active_cell_overlay: tk.Label | None = None
        self.formula_search_running = False
        self.formula_search_queue: queue.Queue | None = None
        self.formula_search_stop_event: threading.Event | None = None
        self.directory_settings_running = False
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
        self._refresh_formula_index_status()
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
            text="Справочники",
            command=self._open_formula_directory_settings,
            style="Secondary.TButton",
        ).grid(row=0, column=2, sticky="e", padx=(0, 8))

        self.formula_index_button = ttk.Button(
            results_header,
            text="Обновить индекс",
            command=self._start_formula_index_update,
            style="Secondary.TButton",
        )
        self.formula_index_button.grid(row=0, column=3, sticky="e", padx=(0, 8))

        self.formula_search_button = ttk.Button(
            results_header,
            text="Найти в формулах",
            command=self._start_formula_search_from_selection,
            style="Secondary.TButton",
        )
        self.formula_search_button.grid(row=0, column=4, sticky="e", padx=(0, 8))

        self.formula_search_stop_button = ttk.Button(
            results_header,
            text="Остановить",
            command=self._stop_formula_search,
            style="Secondary.TButton",
            state="disabled",
        )
        self.formula_search_stop_button.grid(row=0, column=5, sticky="e", padx=(0, 8))

        ttk.Button(
            results_header,
            text="Экспорт CSV",
            command=self._export_current_table_to_csv,
            style="Primary.TButton",
        ).grid(row=0, column=6, sticky="e", padx=(0, 8))

        ttk.Button(
            results_header,
            text="Сбросить фильтры",
            command=self._clear_table_filter,
            style="Secondary.TButton",
        ).grid(row=0, column=7, sticky="e")
        ttk.Label(
            results_header,
            textvariable=self.formula_index_status_var,
            justify="right",
            style="Muted.TLabel",
        ).grid(row=1, column=0, columnspan=8, sticky="e", pady=(6, 0))

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
        self.result_table_context_menu.add_separator()
        self.result_table_context_menu.add_command(
            label="Найти использования этого поля",
            command=self._start_formula_search_from_selection,
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
        self.column_filter_cells = {}

        for index in range(len(FIELD_COLUMNS)):
            self.column_filter_frame.grid_columnconfigure(index, minsize=0)

        for index, column in enumerate(selected_columns):
            width = self.column_widths.get(column, 160)
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
            self.column_filter_cells[column] = filter_cell

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

            resize_handle = tk.Frame(
                filter_cell,
                width=6,
                cursor="sb_h_double_arrow",
                bg="#cbd5e1",
            )
            resize_handle.place(relx=1.0, y=0, x=-3, relheight=1.0)
            resize_handle.bind(
                "<ButtonPress-1>",
                lambda event, selected_column=column: self._start_column_resize(
                    event,
                    selected_column,
                ),
            )
            resize_handle.bind("<B1-Motion>", self._drag_column_resize)
            resize_handle.bind("<ButtonRelease-1>", self._end_column_resize)

        self.column_filter_frame.update_idletasks()
        self.column_filter_canvas.configure(scrollregion=self.column_filter_canvas.bbox("all"))

    def _start_column_resize(self, event: tk.Event, column: str) -> str:
        self.column_resize_state = {
            "column": column,
            "start_x": event.x_root,
            "start_width": self.column_widths.get(column, 160),
        }
        return "break"

    def _drag_column_resize(self, event: tk.Event) -> str:
        if not self.column_resize_state:
            return "break"

        column = self.column_resize_state["column"]
        start_x = self.column_resize_state["start_x"]
        start_width = self.column_resize_state["start_width"]
        new_width = max(80, start_width + event.x_root - start_x)
        self._apply_column_width(column, new_width)
        return "break"

    def _end_column_resize(self, _event: tk.Event) -> str:
        self.column_resize_state = None
        self.status_var.set("Ширина столбца изменена.")
        return "break"

    def _apply_column_width(self, column: str, width: int) -> None:
        width = int(max(80, width))
        self.column_widths[column] = width

        if hasattr(self, "result_table") and column in list(self.result_table["columns"]):
            column_identifier = self._treeview_column_identifier(column)
            if column_identifier is not None:
                self.result_table.column(
                    column_identifier,
                    width=width,
                    minwidth=80,
                    stretch=False,
                )

        columns = list(self.result_table["columns"]) if hasattr(self, "result_table") else []
        if column in columns:
            column_index = columns.index(column)
            self.column_filter_frame.grid_columnconfigure(column_index, minsize=width)

        filter_cell = self.column_filter_cells.get(column)
        if filter_cell is not None:
            filter_cell.configure(width=width)

        if hasattr(self, "column_filter_canvas"):
            self.column_filter_frame.update_idletasks()
            self.column_filter_canvas.configure(
                scrollregion=self.column_filter_canvas.bbox("all")
            )

        self._place_active_cell_overlay()

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

    def _treeview_column_identifier(self, column: str) -> str | None:
        columns = list(self.result_table["columns"])

        if column not in columns:
            return None

        return f"#{columns.index(column) + 1}"

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

        column_identifier = self._treeview_column_identifier(self.active_cell_column)
        if column_identifier is None:
            if self.active_cell_overlay is not None:
                self.active_cell_overlay.place_forget()
            return

        bbox = self.result_table.bbox(self.active_cell_row_id, column_identifier)

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
        self.rendered_rows_by_item_id = {}

        for column in selected_columns:
            width = self.column_widths.get(column, 160)
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
            item_id = self.result_table.insert("", tk.END, values=values)
            self.rendered_rows_by_item_id[item_id] = row

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

    def _selected_result_row(self) -> dict | None:
        if not self._ensure_active_cell() or self.active_cell_row_id is None:
            return None

        return self.rendered_rows_by_item_id.get(self.active_cell_row_id)

    def _selected_field_for_formula_search(self) -> dict | None:
        row = self._selected_result_row()
        if row is None:
            return None

        field: dict = {}
        raw_json = row.get("JSON поля") or row.get("JSON поля в одну строку")
        if raw_json:
            try:
                loaded_field = json.loads(str(raw_json))
                if isinstance(loaded_field, dict):
                    field.update(loaded_field)
            except json.JSONDecodeError:
                field = {}

        if "id" not in field and row.get("ID поля") not in (None, ""):
            field["id"] = row.get("ID поля")

        if not field.get("name") and row.get("Название поля"):
            field["name"] = row.get("Название поля")

        if "type" not in field and row.get("ID типа поля") not in (None, ""):
            field["type"] = row.get("ID типа поля")

        if "names" not in field and row.get("Названия поля по языкам"):
            try:
                names = json.loads(str(row.get("Названия поля по языкам")))
                if isinstance(names, dict):
                    field["names"] = names
            except json.JSONDecodeError:
                pass

        if "id" not in field or not field.get("name"):
            return None

        field["selectedFrom"] = {
            "sourceType": self.current_source_type,
            "sourceTypeName": normalize_source_type(self.current_source_type or ""),
            "sourceId": self.current_source_id,
            "sourceName": self.current_source_name,
        }
        return field

    def _start_formula_search_from_selection(self) -> None:
        if self.formula_search_running:
            messagebox.showinfo(
                "Поиск уже выполняется",
                "Дождитесь завершения текущего поиска по формулам.",
                parent=self.root,
            )
            return

        if not self._has_ready_config():
            messagebox.showwarning(
                "Нужны настройки Planfix",
                "Сначала укажите аккаунт и токен Planfix в настройках.",
                parent=self.root,
            )
            return

        selected_field = self._selected_field_for_formula_search()
        if selected_field is None:
            messagebox.showwarning(
                "Поле не выбрано",
                "Выберите строку с полем в таблице результатов.",
                parent=self.root,
            )
            return

        try:
            save_exports_dir(self.exports_dir_var.get())
            exports_dir = get_exports_dir()
            index_dir = exports_dir / "formula_index"
            index_entries = load_formula_index(index_dir)
            formula_output_dir = exports_dir / "formula_search" / datetime.now().strftime(
                "%Y%m%d_%H%M%S"
            )
            self.exports_dir_var.set(str(exports_dir))
        except FormulaIndexError as error:
            messagebox.showinfo(
                "Индекс формул не готов",
                str(error),
                parent=self.root,
            )
            self.status_var.set(
                "Локальный индекс формул не найден. Нажмите «Обновить индекс»."
            )
            return
        except Exception as error:
            messagebox.showerror(
                "Не удалось подготовить папку результатов",
                str(error),
                parent=self.root,
            )
            return

        self.formula_search_running = True
        self._set_formula_search_controls_state()
        self.formula_search_queue = queue.Queue()
        self.formula_search_stop_event = threading.Event()
        self.status_var.set("Локальный поиск использований поля запущен...")

        def progress_callback(progress: FormulaSearchProgress) -> None:
            if self.formula_search_queue is not None:
                self.formula_search_queue.put(("progress", progress))

        def worker() -> None:
            try:
                usages, result_output_dir = search_formula_index(
                    selected_field,
                    index_entries=index_entries,
                    output_dir=formula_output_dir,
                    progress_callback=progress_callback,
                    cancellation_check=self.formula_search_stop_event.is_set,
                )
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(("done", (usages, result_output_dir)))
            except FormulaSearchCancelled as stopped:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(
                        ("stopped", ([], formula_output_dir, str(stopped)))
                    )
            except FormulaSearchStopped as stopped:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(
                        ("stopped", (stopped.usages, stopped.output_dir, stopped.message))
                    )
            except FormulaSearchError as error:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(("error", str(error)))
            except Exception as error:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(("error", f"Неожиданная ошибка: {error}"))

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(200, self._poll_formula_search_queue)

    def _formula_index_dir(self) -> Path:
        save_exports_dir(self.exports_dir_var.get())
        exports_dir = get_exports_dir()
        self.exports_dir_var.set(str(exports_dir))
        return exports_dir / "formula_index"

    def _refresh_formula_index_status(self) -> None:
        try:
            index_dir = get_exports_dir() / "formula_index"
            status = load_formula_index_status(index_dir)
        except Exception:
            self.formula_index_status_var.set("Индекс формул: статус недоступен")
            return

        if not status:
            self.formula_index_status_var.set("Индекс формул: не создан")
            return

        saved_at = str(status.get("savedAt") or "дата неизвестна")
        entries_count = int(status.get("entriesCount") or 0)
        errors_count = int(status.get("errorsCount") or 0)
        status_name = str(status.get("status") or "unknown")
        self.formula_index_status_var.set(
            "Индекс формул: "
            f"{status_name}, обновлён {saved_at}, "
            f"записей {entries_count}, ошибок {errors_count}"
        )

    def _start_formula_index_update(self) -> None:
        if self.formula_search_running:
            messagebox.showinfo(
                "Операция уже выполняется",
                "Дождитесь завершения текущего поиска или обновления индекса.",
                parent=self.root,
            )
            return

        if not self._has_ready_config():
            messagebox.showwarning(
                "Нужны настройки Planfix",
                "Сначала укажите аккаунт и токен Planfix в настройках.",
                parent=self.root,
            )
            return

        try:
            index_dir = self._formula_index_dir()
        except Exception as error:
            messagebox.showerror(
                "Не удалось подготовить папку индекса",
                str(error),
                parent=self.root,
            )
            return

        self.formula_search_running = True
        self._set_formula_search_controls_state()
        self.formula_search_queue = queue.Queue()
        self.formula_search_stop_event = threading.Event()
        self.status_var.set("Обновление локального индекса формул запущено...")

        def progress_callback(progress: FormulaSearchProgress) -> None:
            if self.formula_search_queue is not None:
                self.formula_search_queue.put(("progress", progress))

        def worker() -> None:
            try:
                entries, output_dir = build_formula_index(
                    dict(self.config),
                    output_dir=index_dir,
                    progress_callback=progress_callback,
                    excluded_directory_ids=load_excluded_formula_search_directory_ids(),
                    cancellation_check=self.formula_search_stop_event.is_set,
                )
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(("index_done", (entries, output_dir)))
            except FormulaIndexStopped as stopped:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(
                        ("index_stopped", (stopped.entries, stopped.output_dir, stopped.message))
                    )
            except Exception as error:
                if self.formula_search_queue is not None:
                    self.formula_search_queue.put(
                        ("index_error", f"Не удалось обновить индекс формул: {error}")
                    )

        threading.Thread(target=worker, daemon=True).start()
        self.root.after(200, self._poll_formula_search_queue)

    def _stop_formula_search(self) -> None:
        if not self.formula_search_running or self.formula_search_stop_event is None:
            return

        self.formula_search_stop_event.set()
        self.status_var.set(
            "Останавливаю текущую операцию... Текущий HTTP-запрос завершится, "
            "затем будут сохранены частичные результаты."
        )
        if hasattr(self, "formula_search_stop_button"):
            self.formula_search_stop_button.configure(state="disabled")

    def _set_formula_search_controls_state(self) -> None:
        if not hasattr(self, "formula_search_button"):
            return

        search_state = "disabled" if self.formula_search_running else "normal"
        stop_state = "normal" if self.formula_search_running else "disabled"
        self.formula_search_button.configure(state=search_state)
        if hasattr(self, "formula_index_button"):
            self.formula_index_button.configure(state=search_state)
        if hasattr(self, "formula_search_stop_button"):
            self.formula_search_stop_button.configure(state=stop_state)

    def _poll_formula_search_queue(self) -> None:
        if self.formula_search_queue is None:
            return

        try:
            while True:
                event_type, payload = self.formula_search_queue.get_nowait()
                if event_type == "progress":
                    self._handle_formula_search_progress(payload)
                elif event_type == "done":
                    usages, output_dir = payload
                    output_path = Path(output_dir)
                    status_message = self._formula_search_result_status_message(output_path)
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    if status_message:
                        self.status_var.set(
                            "Поиск завершён с предупреждениями. "
                            f"Найдено использований: {len(usages)}."
                        )
                    else:
                        self.status_var.set(
                            f"Поиск завершён. Найдено использований: {len(usages)}."
                        )
                    self._show_formula_search_results(
                        usages,
                        output_path,
                        status_message=status_message,
                    )
                elif event_type == "stopped":
                    usages, output_dir, message = payload
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    self.status_var.set(
                        "Поиск остановлен пользователем. "
                        f"Сохранены частичные результаты: {len(usages)}."
                    )
                    self._show_formula_search_results(
                        usages,
                        Path(output_dir),
                        status_message=(
                            f"{message} Сохранены частичные результаты."
                        ),
                    )
                elif event_type == "index_done":
                    entries, output_dir = payload
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    status = load_formula_index_status(Path(output_dir))
                    self._refresh_formula_index_status()
                    errors_count = int(status.get("errorsCount") or 0)
                    if errors_count:
                        self.status_var.set(
                            "Индекс формул обновлён с предупреждениями. "
                            f"Записей: {len(entries)}, ошибок: {errors_count}."
                        )
                    else:
                        self.status_var.set(
                            f"Индекс формул обновлён. Записей: {len(entries)}."
                        )
                elif event_type == "index_stopped":
                    entries, output_dir, message = payload
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    self._refresh_formula_index_status()
                    self.status_var.set(
                        "Обновление индекса остановлено. "
                        f"Сохранён частичный индекс: {len(entries)} записей. "
                        f"Папка: {output_dir}. {message}"
                    )
                elif event_type == "index_error":
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    self._refresh_formula_index_status()
                    self.status_var.set("Обновление индекса формул завершилось ошибкой.")
                    messagebox.showerror(
                        "Ошибка обновления индекса",
                        str(payload),
                        parent=self.root,
                    )
                elif event_type == "error":
                    self.formula_search_running = False
                    self.formula_search_stop_event = None
                    self._set_formula_search_controls_state()
                    self.status_var.set("Поиск использований поля завершился ошибкой.")
                    messagebox.showerror(
                        "Ошибка поиска",
                        str(payload),
                        parent=self.root,
                    )
        except queue.Empty:
            pass

        if self.formula_search_running:
            self.root.after(200, self._poll_formula_search_queue)

    def _handle_formula_search_progress(self, progress: FormulaSearchProgress) -> None:
        parts = [progress.stage]

        if progress.total_fields:
            parts.append(f"проверено {progress.checked_fields}/{progress.total_fields}")
        elif progress.checked_fields:
            parts.append(f"проверено {progress.checked_fields}")

        parts.append(f"найдено {progress.matches_found}")

        if progress.last_request_at:
            parts.append(f"последний запрос {progress.last_request_at}")

        if progress.output_file:
            parts.append(f"output: {progress.output_file}")

        if progress.message:
            parts.append(progress.message)

        self.status_var.set(" | ".join(parts))

    def _formula_search_result_status_message(self, output_dir: Path) -> str:
        run_status_file = output_dir / "run_status.json"
        if not run_status_file.exists():
            return ""

        try:
            with open(run_status_file, "r", encoding="utf-8") as file:
                run_status = json.load(file)
        except (OSError, json.JSONDecodeError):
            return ""

        errors_count = int(run_status.get("errorsCount") or 0)
        if errors_count <= 0:
            return ""

        return (
            "Поиск завершён с предупреждениями. "
            f"Ошибок справочников: {errors_count}. "
            "Подробности сохранены в errors.json."
        )

    def _show_formula_search_results(
        self,
        usages: list[FormulaUsage],
        output_dir: Path,
        status_message: str = "",
    ) -> None:
        results_window = tk.Toplevel(self.root)
        results_window.title("Использования поля в формулах")
        results_window.geometry("1180x560")
        results_window.minsize(980, 420)
        results_window.configure(bg=BG)

        frame = self._create_card(results_window)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        ttk.Label(
            frame,
            text=f"Найдено использований: {len(usages)}",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            frame,
            text=f"Папка результата: {output_dir}",
            style="Muted.TLabel",
        ).grid(row=1, column=0, sticky="w", pady=(4, 10))

        table_row = 2
        if status_message:
            ttk.Label(
                frame,
                text=status_message,
                style="Muted.TLabel",
            ).grid(row=2, column=0, sticky="w", pady=(0, 10))
            table_row = 3
        frame.grid_rowconfigure(table_row, weight=1)

        columns = [
            "Уверенность",
            "Где найдено",
            "Название вычисляемого поля",
            "Название справочника",
            "Ключ записи справочника",
            "Название записи справочника",
            "Название текстового поля справочника",
            "Найденная ссылка",
            "Совпавший сегмент",
        ]
        table_frame = tk.Frame(frame, bg=CARD_BG)
        table_frame.grid(row=table_row, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        results_table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Results.Treeview",
        )
        results_table.grid(row=0, column=0, sticky="nsew")

        column_widths = {
            "Уверенность": 150,
            "Где найдено": 130,
            "Название вычисляемого поля": 220,
            "Название справочника": 230,
            "Ключ записи справочника": 140,
            "Название записи справочника": 260,
            "Название текстового поля справочника": 230,
            "Найденная ссылка": 260,
            "Совпавший сегмент": 180,
        }
        for column in columns:
            results_table.heading(column, text=column)
            results_table.column(
                column,
                width=column_widths.get(column, 180),
                minwidth=90,
                stretch=False,
                anchor="w",
            )

        for usage in usages:
            row = usage_to_output_row(usage)
            values = [self._format_table_value(row.get(column, "")) for column in columns]
            results_table.insert("", tk.END, values=values)

        vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=results_table.yview,
        )
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        horizontal_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="horizontal",
            command=results_table.xview,
        )
        horizontal_scrollbar.grid(row=1, column=0, sticky="ew")
        results_table.configure(
            yscrollcommand=vertical_scrollbar.set,
            xscrollcommand=horizontal_scrollbar.set,
        )

        if not usages:
            ttk.Label(
                frame,
                text="Использования выбранного поля в проверенных формулах не найдены.",
                style="Muted.TLabel",
            ).grid(row=table_row + 1, column=0, sticky="w", pady=(10, 0))

        buttons_frame = tk.Frame(frame, bg=CARD_BG)
        buttons_frame.grid(row=table_row + 2, column=0, sticky="e", pady=(12, 0))

        ttk.Button(
            buttons_frame,
            text="Открыть папку",
            command=lambda: os.startfile(output_dir),
            style="Secondary.TButton",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons_frame,
            text="Копировать путь CSV",
            command=lambda: self._copy_text_to_clipboard(str(output_dir / "results.csv")),
            style="Secondary.TButton",
        ).pack(side="left", padx=(0, 8))
        ttk.Button(
            buttons_frame,
            text="Закрыть",
            command=results_window.destroy,
            style="Primary.TButton",
        ).pack(side="left")

    def _copy_text_to_clipboard(self, text: str) -> None:
        self.root.clipboard_clear()
        self.root.clipboard_append(text)
        self.status_var.set("Путь скопирован.")

    def _open_formula_directory_settings(self) -> None:
        if not self._has_ready_config():
            messagebox.showwarning(
                "Нужны настройки Planfix",
                "Сначала укажите аккаунт и токен Planfix в настройках.",
                parent=self.root,
            )
            return

        settings_window = tk.Toplevel(self.root)
        settings_window.title("Справочники для поиска формул")
        settings_window.geometry("920x560")
        settings_window.minsize(760, 420)
        settings_window.configure(bg=BG)

        frame = self._create_card(settings_window)
        frame.pack(fill="both", expand=True, padx=16, pady=16)
        frame.grid_columnconfigure(0, weight=1)
        frame.grid_rowconfigure(2, weight=1)

        status_var = tk.StringVar(value="Список справочников ещё не загружен.")
        filter_var = tk.StringVar(value="")
        excluded_ids = set(load_excluded_formula_search_directory_ids())
        directories: list[dict] = []
        load_queue: queue.Queue = queue.Queue()

        header_frame = tk.Frame(frame, bg=CARD_BG)
        header_frame.grid(row=0, column=0, sticky="ew")
        header_frame.grid_columnconfigure(1, weight=1)

        ttk.Label(
            header_frame,
            text="Справочники для поиска формул",
            style="CardTitle.TLabel",
        ).grid(row=0, column=0, sticky="w")
        ttk.Label(
            header_frame,
            textvariable=status_var,
            justify="right",
            style="Muted.TLabel",
        ).grid(row=0, column=1, sticky="e", padx=(12, 0))

        controls_frame = tk.Frame(frame, bg=CARD_BG)
        controls_frame.grid(row=1, column=0, sticky="ew", pady=(12, 10))
        controls_frame.grid_columnconfigure(0, weight=1)

        filter_entry = ttk.Entry(
            controls_frame,
            textvariable=filter_var,
            style="App.TEntry",
        )
        filter_entry.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self._bind_entry_shortcuts(filter_entry)

        load_button = ttk.Button(
            controls_frame,
            text="Загрузить список",
            style="Secondary.TButton",
        )
        load_button.grid(row=0, column=1, sticky="e", padx=(0, 8))

        toggle_button = ttk.Button(
            controls_frame,
            text="Переключить выбранные",
            style="Secondary.TButton",
        )
        toggle_button.grid(row=0, column=2, sticky="e", padx=(0, 8))

        include_all_button = ttk.Button(
            controls_frame,
            text="Включить все",
            style="Secondary.TButton",
        )
        include_all_button.grid(row=0, column=3, sticky="e")

        table_frame = tk.Frame(frame, bg=CARD_BG)
        table_frame.grid(row=2, column=0, sticky="nsew")
        table_frame.grid_columnconfigure(0, weight=1)
        table_frame.grid_rowconfigure(0, weight=1)

        columns = ["Искать", "ID", "Название", "Группа", "Текстовых полей"]
        directories_table = ttk.Treeview(
            table_frame,
            columns=columns,
            show="headings",
            style="Results.Treeview",
            selectmode="extended",
        )
        directories_table.grid(row=0, column=0, sticky="nsew")
        widths = {
            "Искать": 90,
            "ID": 90,
            "Название": 300,
            "Группа": 240,
            "Текстовых полей": 130,
        }
        for column in columns:
            directories_table.heading(column, text=column)
            directories_table.column(
                column,
                width=widths.get(column, 160),
                minwidth=80,
                stretch=column in {"Название", "Группа"},
                anchor="w",
            )

        vertical_scrollbar = ttk.Scrollbar(
            table_frame,
            orient="vertical",
            command=directories_table.yview,
        )
        vertical_scrollbar.grid(row=0, column=1, sticky="ns")
        directories_table.configure(yscrollcommand=vertical_scrollbar.set)

        buttons_frame = tk.Frame(frame, bg=CARD_BG)
        buttons_frame.grid(row=3, column=0, sticky="e", pady=(12, 0))

        save_button = ttk.Button(
            buttons_frame,
            text="Сохранить",
            style="Primary.TButton",
        )
        save_button.pack(side="left", padx=(0, 8))
        close_button = ttk.Button(
            buttons_frame,
            text="Закрыть",
            style="Secondary.TButton",
        )
        close_button.pack(side="left")

        def group_name(directory: dict) -> str:
            group = directory.get("group")
            if isinstance(group, dict):
                return str(group.get("name", "") or "")
            return ""

        def text_field_count(directory: dict) -> int:
            fields = directory.get("fields")
            if not isinstance(fields, list):
                return 0
            return len(
                [
                    field
                    for field in fields
                    if isinstance(field, dict) and field.get("type") == 2
                ]
            )

        def directory_matches_filter(directory: dict) -> bool:
            filter_text = filter_var.get().strip().casefold()
            if not filter_text:
                return True

            values = [
                str(directory.get("id", "")),
                str(directory.get("name", "")),
                group_name(directory),
            ]
            return any(filter_text in value.casefold() for value in values)

        def refresh_table() -> None:
            directories_table.delete(*directories_table.get_children())
            for directory in directories:
                if not directory_matches_filter(directory):
                    continue

                directory_id = str(directory.get("id", ""))
                directories_table.insert(
                    "",
                    tk.END,
                    iid=directory_id,
                    values=[
                        "Нет" if directory_id in excluded_ids else "Да",
                        directory_id,
                        self._format_table_value(directory.get("name", "")),
                        self._format_table_value(group_name(directory)),
                        text_field_count(directory),
                    ],
                )

            status_var.set(
                f"Загружено: {len(directories)} | "
                f"исключено: {len(excluded_ids)}"
            )

        def toggle_selected() -> None:
            selected_items = directories_table.selection()
            if not selected_items:
                return

            for item_id in selected_items:
                directory_id = str(item_id)
                if directory_id in excluded_ids:
                    excluded_ids.remove(directory_id)
                else:
                    excluded_ids.add(directory_id)

            refresh_table()

        def include_all() -> None:
            excluded_ids.clear()
            refresh_table()

        def save_settings() -> None:
            try:
                save_excluded_formula_search_directory_ids(excluded_ids)
            except Exception as error:
                messagebox.showerror(
                    "Не удалось сохранить настройки",
                    str(error),
                    parent=settings_window,
                )
                return

            self.status_var.set(
                f"Настройки справочников сохранены. Исключено: {len(excluded_ids)}."
            )
            saved_at = datetime.now().strftime("%H:%M:%S")
            status_var.set(f"Сохранено в {saved_at}. Исключено: {len(excluded_ids)}")
            save_button.configure(text=f"Сохранено {saved_at}")

            def restore_save_button_text() -> None:
                if settings_window.winfo_exists() and not self.directory_settings_running:
                    save_button.configure(text="Сохранить")

            settings_window.after(2200, restore_save_button_text)

        def set_loading_state(is_loading: bool) -> None:
            self.directory_settings_running = is_loading
            state = "disabled" if is_loading else "normal"
            load_button.configure(state=state)
            save_button.configure(state=state)

        def progress_callback(progress: FormulaSearchProgress) -> None:
            load_queue.put(("progress", progress))

        def start_loading() -> None:
            if self.directory_settings_running:
                return

            set_loading_state(True)
            status_var.set("Загружаю список справочников Planfix...")

            def worker() -> None:
                try:
                    client = RateLimitedPlanfixClient(
                        dict(self.config),
                        progress_callback=progress_callback,
                    )
                    loaded_directories = load_directories(client)
                    load_queue.put(("done", loaded_directories))
                except Exception as error:
                    load_queue.put(("error", str(error)))

            threading.Thread(target=worker, daemon=True).start()
            settings_window.after(200, poll_queue)

        def poll_queue() -> None:
            try:
                while True:
                    event_type, payload = load_queue.get_nowait()
                    if event_type == "progress":
                        progress = payload
                        parts = [progress.stage]
                        if progress.last_request_at:
                            parts.append(f"последний запрос {progress.last_request_at}")
                        if progress.message:
                            parts.append(progress.message)
                        status_var.set(" | ".join(parts))
                    elif event_type == "done":
                        directories.clear()
                        directories.extend(
                            sorted(
                                payload,
                                key=lambda directory: (
                                    group_name(directory).casefold(),
                                    str(directory.get("name", "")).casefold(),
                                    str(directory.get("id", "")),
                                ),
                            )
                        )
                        set_loading_state(False)
                        refresh_table()
                    elif event_type == "error":
                        set_loading_state(False)
                        status_var.set("Не удалось загрузить список справочников.")
                        messagebox.showerror(
                            "Ошибка загрузки справочников",
                            str(payload),
                            parent=settings_window,
                        )
            except queue.Empty:
                pass

            if self.directory_settings_running and settings_window.winfo_exists():
                settings_window.after(200, poll_queue)

        def on_close() -> None:
            if self.directory_settings_running:
                messagebox.showinfo(
                    "Загрузка выполняется",
                    "Дождитесь завершения загрузки списка справочников.",
                    parent=settings_window,
                )
                return
            settings_window.destroy()

        load_button.configure(command=start_loading)
        toggle_button.configure(command=toggle_selected)
        include_all_button.configure(command=include_all)
        save_button.configure(command=save_settings)
        close_button.configure(command=on_close)
        directories_table.bind("<Double-1>", lambda _event: toggle_selected())
        directories_table.bind("<space>", lambda _event: toggle_selected())
        filter_var.trace_add("write", lambda *_args: refresh_table())
        settings_window.protocol("WM_DELETE_WINDOW", on_close)
        start_loading()

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
            self._refresh_formula_index_status()
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
