from main_window import MainWindow
from planfix_export_fields_interactive import load_config
from settings import has_complete_settings
from version import APP_VERSION


def main() -> None:
    config = load_config() if has_complete_settings() else {
        "account": "",
        "token": "",
        "base_url": "",
    }
    window = MainWindow(config)
    window.show()


if __name__ == "__main__":
    main()
