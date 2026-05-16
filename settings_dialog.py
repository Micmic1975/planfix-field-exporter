import tkinter as tk
from tkinter import messagebox

from settings import (
    load_account,
    load_token,
    save_account,
    save_token,
)


class SettingsDialog:
    def __init__(self, parent: tk.Misc | None = None) -> None:
        self.parent = parent
        self.is_standalone = parent is None

        if self.is_standalone:
            self.window = tk.Tk()
        else:
            self.window = tk.Toplevel(parent)
            self.window.transient(parent)
            self.window.grab_set()

        self.window.title("Настройки Planfix Field Exporter")
        self.window.resizable(False, False)

        self.saved = False

        self.account_var = tk.StringVar(master=self.window)
        self.token_var = tk.StringVar(master=self.window)

        self._build_ui()
        self._load_existing_values()

    def _build_ui(self) -> None:
        frame = tk.Frame(self.window, padx=16, pady=16)
        frame.pack(fill="both", expand=True)

        tk.Label(frame, text="Аккаунт Planfix").grid(
            row=0,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        account_entry = tk.Entry(
            frame,
            textvariable=self.account_var,
            width=42,
        )
        account_entry.grid(
            row=1,
            column=0,
            sticky="ew",
            pady=(0, 4),
        )

        tk.Label(
            frame,
            text="Например: engineering  (без .planfix.ru)",
            justify="left",
            fg="#555555",
        ).grid(
            row=2,
            column=0,
            sticky="w",
            pady=(0, 12),
        )

        tk.Label(frame, text="Токен доступа").grid(
            row=3,
            column=0,
            sticky="w",
            pady=(0, 4),
        )
        token_entry = tk.Entry(
            frame,
            textvariable=self.token_var,
            width=42,
            show="*",
        )
        token_entry.grid(
            row=4,
            column=0,
            sticky="ew",
            pady=(0, 4),
        )

        tk.Label(
            frame,
            text="Вставьте только сам токен, без слова Bearer.",
            justify="left",
            fg="#555555",
        ).grid(
            row=5,
            column=0,
            sticky="w",
            pady=(0, 12),
        )

        help_text = (
            "Токен будет сохранён в системном хранилище Windows,\n"
            "а не в открытом текстовом файле."
        )
        tk.Label(
            frame,
            text=help_text,
            justify="left",
            fg="#555555",
        ).grid(
            row=6,
            column=0,
            sticky="w",
            pady=(0, 16),
        )

        button_frame = tk.Frame(frame)
        button_frame.grid(row=7, column=0, sticky="e")

        tk.Button(
            button_frame,
            text="Сохранить",
            width=12,
            command=self._save,
        ).pack(side="left")

        self.window.bind("<Return>", lambda _event: self._save())
        self._bind_entry_shortcuts(account_entry)
        self._bind_entry_shortcuts(token_entry)
        account_entry.focus_set()

    def _bind_entry_shortcuts(self, entry: tk.Entry) -> None:
        entry.bind("<Control-KeyPress>", lambda event: self._handle_control_shortcut(entry, event))

    @staticmethod
    def _handle_virtual_event(entry: tk.Entry, virtual_event: str) -> str:
        entry.event_generate(virtual_event)
        return "break"

    def _handle_control_shortcut(self, entry: tk.Entry, event: tk.Event) -> str | None:
        # На Windows у физических клавиш C / V / X одинаковые keycode
        # независимо от текущей языковой раскладки клавиатуры.
        shortcut_by_keycode = {
            67: "<<Copy>>",
            86: "<<Paste>>",
            88: "<<Cut>>",
        }

        virtual_event = shortcut_by_keycode.get(event.keycode)

        if not virtual_event:
            return None

        return self._handle_virtual_event(entry, virtual_event)

    def _load_existing_values(self) -> None:
        account = load_account()

        if not account:
            return

        self.account_var.set(account)

        token = load_token(account)
        if token:
            self.token_var.set(token)

    def _save(self) -> None:
        try:
            account = self.account_var.get()
            token = self.token_var.get()

            save_account(account)
            save_token(account, token)
        except Exception as error:
            messagebox.showerror(
                "Не удалось сохранить настройки",
                str(error),
                parent=self.window,
            )
            return

        self.saved = True
        messagebox.showinfo(
            "Настройки сохранены",
            "Аккаунт и токен успешно сохранены.",
            parent=self.window,
        )
        self.window.destroy()

    def show(self) -> bool:
        if self.is_standalone:
            self.window.mainloop()
        else:
            self.window.wait_window()

        return self.saved


def open_settings_dialog(parent: tk.Misc | None = None) -> bool:
    dialog = SettingsDialog(parent)
    return dialog.show()


if __name__ == "__main__":
    open_settings_dialog()
