import tkinter as tk
from tkinter import ttk


class SearchableDropdown(ttk.Frame):
    def __init__(self, master, width: int = 68, **kwargs) -> None:
        super().__init__(master, **kwargs)

        self.value_var = tk.StringVar(master=self)
        self.items: list[str] = []
        self.filtered_items: list[str] = []
        self.on_select_callback = None

        self.entry = ttk.Entry(
            self,
            textvariable=self.value_var,
            width=width,
            style="App.TEntry",
        )
        self.entry.pack(fill="x")

        self.popup = None
        self.listbox = None
        self.suppress_next_focus_popup = False

        self.entry.bind("<KeyRelease>", self._on_key_release)
        self.entry.bind("<FocusIn>", self._on_focus_in)
        self.entry.bind("<Button-1>", self._on_click)
        self.entry.bind("<Down>", self._focus_first_item)
        self.entry.bind("<Return>", self._select_entry_value)
        self.entry.bind("<Escape>", lambda _event: self.hide_popup())
        self.entry.bind("<Control-KeyPress>", self._handle_control_shortcut)
        self.top_level = self.winfo_toplevel()
        self.top_level.bind_all("<Button-1>", self._handle_global_click, add="+")
        self.top_level.bind("<FocusOut>", self._handle_top_level_focus_out, add="+")

    def set_items(self, items: list[str]) -> None:
        self.items = list(items)
        self.filtered_items = list(items)
        self.value_var.set("")

    def clear(self) -> None:
        self.items = []
        self.filtered_items = []
        self.value_var.set("")
        self.hide_popup()

    def get(self) -> str:
        return self.value_var.get()

    def set(self, value: str) -> None:
        self.value_var.set(value)

    def bind_on_select(self, callback) -> None:
        self.on_select_callback = callback

    def _on_focus_in(self, _event) -> None:
        if self.suppress_next_focus_popup:
            self.suppress_next_focus_popup = False
            return

        if self.items:
            self.filtered_items = list(self.items)
            self.show_popup()

    def _on_click(self, _event) -> None:
        if self.items:
            self.filtered_items = list(self.items)
            self.show_popup()

    def _on_key_release(self, event) -> None:
        if event.keysym in {"Up", "Down", "Return", "Escape"}:
            return

        self._apply_filter()
        self.show_popup()

    def _apply_filter(self) -> None:
        search_text = self.value_var.get().strip().casefold()

        if search_text:
            self.filtered_items = [
                item
                for item in self.items
                if search_text in item.casefold()
            ]
        else:
            self.filtered_items = list(self.items)

        self._refresh_listbox()

    def show_popup(self) -> None:
        if not self.filtered_items:
            self.hide_popup()
            return

        if self.popup is None or not self.popup.winfo_exists():
            self.popup = tk.Toplevel(self)
            self.popup.overrideredirect(True)
            self.popup.attributes("-topmost", True)
            self.popup.configure(bg="#d7dee8")

            self.listbox = tk.Listbox(
                self.popup,
                height=min(10, len(self.filtered_items)),
                activestyle="none",
                background="#ffffff",
                borderwidth=0,
                exportselection=False,
                font=("Segoe UI", 10),
                foreground="#182230",
                highlightbackground="#d7dee8",
                highlightcolor="#3b82f6",
                highlightthickness=1,
                relief="flat",
                selectbackground="#e8f1ff",
                selectforeground="#0f172a",
            )
            self.listbox.pack(fill="both", expand=True, padx=1, pady=1)
            self.listbox.bind("<ButtonPress-1>", self._select_clicked_item)
            self.listbox.bind("<Return>", self._select_current_item)
            self.listbox.bind("<Escape>", lambda _event: self.hide_popup())

        self._position_popup()
        self._refresh_listbox()

    def hide_popup(self) -> None:
        if self.popup is not None and self.popup.winfo_exists():
            self.popup.destroy()

        self.popup = None
        self.listbox = None

    def _position_popup(self) -> None:
        self.update_idletasks()
        x = self.entry.winfo_rootx()
        y = self.entry.winfo_rooty() + self.entry.winfo_height() + 4
        width = self.entry.winfo_width()
        height = min(240, 28 * max(1, len(self.filtered_items)) + 2)
        self.popup.geometry(f"{width}x{height}+{x}+{y}")

    def _refresh_listbox(self) -> None:
        if self.listbox is None:
            return

        self.listbox.delete(0, tk.END)

        for item in self.filtered_items:
            self.listbox.insert(tk.END, item)

        if self.filtered_items:
            self.listbox.selection_set(0)

    def _focus_first_item(self, _event):
        if not self.filtered_items:
            return None

        self.show_popup()

        if self.listbox is not None:
            self.listbox.focus_set()
            self.listbox.selection_clear(0, tk.END)
            self.listbox.selection_set(0)
            self.listbox.activate(0)

        return "break"

    def _select_current_item(self, _event=None):
        if self.listbox is None:
            return "break"

        selection = self.listbox.curselection()

        if not selection:
            return "break"

        self._select_value(self.listbox.get(selection[0]))
        return "break"

    def _select_entry_value(self, _event=None):
        entered_value = self.value_var.get()

        if entered_value in self.items:
            self._select_value(entered_value)
            return "break"

        self._apply_filter()

        if self.filtered_items:
            self._select_value(self.filtered_items[0])
            return "break"

        return "break"

    def _select_value(self, selected_value: str) -> None:
        self.value_var.set(selected_value)
        self.suppress_next_focus_popup = True
        self.hide_popup()
        self.entry.focus_set()

        if self.on_select_callback is not None:
            self.on_select_callback(selected_value)

    def _select_clicked_item(self, event):
        if self.listbox is None:
            return "break"

        clicked_index = self.listbox.nearest(event.y)

        if clicked_index < 0:
            return "break"

        self.listbox.selection_clear(0, tk.END)
        self.listbox.selection_set(clicked_index)
        self.listbox.activate(clicked_index)
        self._select_value(self.listbox.get(clicked_index))

        return "break"

    def _handle_control_shortcut(self, event):
        shortcut_by_keycode = {
            65: self._select_all,
        }

        handler = shortcut_by_keycode.get(event.keycode)

        if handler is None:
            return None

        handler()
        return "break"

    def _select_all(self) -> None:
        self.entry.selection_range(0, tk.END)
        self.entry.icursor(tk.END)

    def _handle_global_click(self, event) -> None:
        if self.popup is None or not self.popup.winfo_exists():
            return

        clicked_widget = event.widget

        if clicked_widget is self.entry:
            return

        if self.listbox is not None and clicked_widget is self.listbox:
            return

        self.hide_popup()

    def _handle_top_level_focus_out(self, _event) -> None:
        self.top_level.after(10, self._close_if_app_inactive)

    def _close_if_app_inactive(self) -> None:
        if not self.top_level.focus_get():
            self.hide_popup()
