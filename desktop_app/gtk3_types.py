from __future__ import annotations

from typing import Callable


class Gtk:
    class StatusIcon:
        @staticmethod
        def new_from_file(filename: str) -> Gtk.StatusIcon:
            raise NotImplementedError

        @staticmethod
        def position_menu(
            menu: Gtk.Menu,
            x: int,
            y: int,
            push_in: bool,
            user_data: object | None,
        ) -> None:
            raise NotImplementedError

        def set_visible(self, visible: bool) -> None:
            raise NotImplementedError

        def set_tooltip_text(self, text: str) -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: Callable[..., object]) -> None:
            raise NotImplementedError

    class Menu:
        def __init__(self) -> None:
            raise NotImplementedError

        def append(self, child: Gtk.MenuItem) -> None:
            raise NotImplementedError

        def show_all(self) -> None:
            raise NotImplementedError

        def popup_at_pointer(self, event: object | None) -> None:
            raise NotImplementedError

        def popup(
            self,
            parent_menu_shell: object | None,
            parent_menu_item: object | None,
            func: object | None,
            data: object | None,
            button: int,
            activate_time: int,
        ) -> None:
            raise NotImplementedError

    class MenuItem:
        def __init__(self, label: str = "") -> None:
            raise NotImplementedError

        def connect(self, name: str, callback: Callable[..., object]) -> None:
            raise NotImplementedError

    @staticmethod
    def main() -> None:
        raise NotImplementedError

    @staticmethod
    def main_quit() -> None:
        raise NotImplementedError
