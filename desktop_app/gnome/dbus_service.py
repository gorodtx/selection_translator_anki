from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import importlib

from desktop_app import gtk_types
from desktop_app.controllers.settings_controller import AnkiActionResult, AnkiStatus
from desktop_app.anki import AnkiListResult

gi = importlib.import_module("gi")
require_version = getattr(gi, "require_version", None)
if callable(require_version):
    require_version("Gio", "2.0")
    require_version("GLib", "2.0")
Gio = importlib.import_module("gi.repository.Gio")
GLib = importlib.import_module("gi.repository.GLib")
VariantType: type[gtk_types.GLib.Variant] = getattr(GLib, "Variant")

BUS_NAME = "com.translator.desktop"
OBJECT_PATH = "/com/translator/desktop"
INTERFACE_XML = """
<node>
  <interface name="com.translator.desktop">
    <method name="Translate">
      <arg type="s" name="text" direction="in"/>
    </method>
    <method name="ShowSettings"/>
    <method name="ShowHistory"/>
    <method name="GetAnkiStatus">
      <arg type="s" name="model_status" direction="out"/>
      <arg type="s" name="deck_status" direction="out"/>
      <arg type="s" name="deck_name" direction="out"/>
    </method>
    <method name="CreateAnkiModel">
      <arg type="s" name="message" direction="out"/>
      <arg type="s" name="model_status" direction="out"/>
      <arg type="s" name="deck_status" direction="out"/>
      <arg type="s" name="deck_name" direction="out"/>
    </method>
    <method name="ListAnkiDecks">
      <arg type="as" name="decks" direction="out"/>
      <arg type="s" name="error" direction="out"/>
    </method>
    <method name="SelectAnkiDeck">
      <arg type="s" name="deck" direction="in"/>
      <arg type="s" name="message" direction="out"/>
      <arg type="s" name="model_status" direction="out"/>
      <arg type="s" name="deck_status" direction="out"/>
      <arg type="s" name="deck_name" direction="out"/>
    </method>
    <method name="SaveSettings">
      <arg type="s" name="message" direction="out"/>
      <arg type="s" name="model_status" direction="out"/>
      <arg type="s" name="deck_status" direction="out"/>
      <arg type="s" name="deck_name" direction="out"/>
    </method>
  </interface>
</node>
"""


@dataclass(slots=True)
class DbusService:
    connection: gtk_types.Gio.DBusConnection
    registration_id: int
    on_translate: Callable[[str], None]
    on_show_settings: Callable[[], None]
    on_show_history: Callable[[], None]
    on_get_anki_status: Callable[[Callable[[AnkiStatus], None]], None]
    on_create_model: Callable[[Callable[[AnkiActionResult], None]], None]
    on_list_decks: Callable[[Callable[[AnkiListResult], None]], None]
    on_select_deck: Callable[[str, Callable[[AnkiActionResult], None]], None]
    on_save_settings: Callable[[Callable[[AnkiActionResult], None]], None]

    @classmethod
    def register(
        cls,
        *,
        app: gtk_types.Gtk.Application,
        on_translate: Callable[[str], None],
        on_show_settings: Callable[[], None],
        on_show_history: Callable[[], None],
        on_get_anki_status: Callable[[Callable[[AnkiStatus], None]], None],
        on_create_model: Callable[[Callable[[AnkiActionResult], None]], None],
        on_list_decks: Callable[[Callable[[AnkiListResult], None]], None],
        on_select_deck: Callable[[str, Callable[[AnkiActionResult], None]], None],
        on_save_settings: Callable[[Callable[[AnkiActionResult], None]], None],
    ) -> "DbusService | None":
        connection = app.get_dbus_connection()
        if connection is None:
            return None
        node = Gio.DBusNodeInfo.new_for_xml(INTERFACE_XML)
        interface = node.interfaces[0]
        service = cls(
            connection=connection,
            registration_id=0,
            on_translate=on_translate,
            on_show_settings=on_show_settings,
            on_show_history=on_show_history,
            on_get_anki_status=on_get_anki_status,
            on_create_model=on_create_model,
            on_list_decks=on_list_decks,
            on_select_deck=on_select_deck,
            on_save_settings=on_save_settings,
        )
        registration_id = connection.register_object(
            OBJECT_PATH,
            interface,
            service._on_method_call,
        )
        if registration_id == 0:
            return None
        service.registration_id = registration_id
        return service

    def close(self) -> None:
        try:
            self.connection.unregister_object(self.registration_id)
        except Exception:
            pass

    def _on_method_call(
        self,
        _connection: gtk_types.Gio.DBusConnection,
        _sender: str | None,
        _object_path: str,
        _interface_name: str,
        method_name: str,
        parameters: object,
        invocation: gtk_types.Gio.DBusMethodInvocation,
    ) -> None:
        if method_name == "Translate":
            text = _extract_text(parameters)
            if text is not None:
                GLib.idle_add(self._dispatch_translate, text)
            invocation.return_value(VariantType("()", ()))
            return
        if method_name == "ShowSettings":
            GLib.idle_add(self._dispatch_settings)
            invocation.return_value(VariantType("()", ()))
            return
        if method_name == "ShowHistory":
            GLib.idle_add(self._dispatch_history)
            invocation.return_value(VariantType("()", ()))
            return
        if method_name == "GetAnkiStatus":
            self.on_get_anki_status(
                lambda status: invocation.return_value(_status_variant(status))
            )
            return
        if method_name == "CreateAnkiModel":
            self.on_create_model(
                lambda result: invocation.return_value(_action_variant(result))
            )
            return
        if method_name == "ListAnkiDecks":
            self.on_list_decks(
                lambda result: invocation.return_value(_deck_list_variant(result))
            )
            return
        if method_name == "SelectAnkiDeck":
            deck = _extract_text(parameters)
            if deck is None:
                invocation.return_value(_action_variant(_empty_action()))
                return
            self.on_select_deck(
                deck,
                lambda result: invocation.return_value(_action_variant(result)),
            )
            return
        if method_name == "SaveSettings":
            self.on_save_settings(
                lambda result: invocation.return_value(_action_variant(result))
            )
            return
        invocation.return_value(VariantType("()", ()))

    def _dispatch_translate(self, text: str) -> bool:
        self.on_translate(text)
        return False

    def _dispatch_settings(self) -> bool:
        self.on_show_settings()
        return False

    def _dispatch_history(self) -> bool:
        self.on_show_history()
        return False


def _extract_text(parameters: object) -> str | None:
    if isinstance(parameters, VariantType):
        try:
            unpacked: object = parameters.unpack()
        except Exception:
            return None
        if isinstance(unpacked, tuple) and unpacked and isinstance(unpacked[0], str):
            return unpacked[0]
        return None
    return None


def _status_variant(status: AnkiStatus) -> gtk_types.GLib.Variant:
    return VariantType(
        "(sss)", (status.model_status, status.deck_status, status.deck_name)
    )


def _action_variant(result: AnkiActionResult) -> gtk_types.GLib.Variant:
    status = result.status
    return VariantType(
        "(ssss)",
        (result.message, status.model_status, status.deck_status, status.deck_name),
    )


def _deck_list_variant(result: AnkiListResult) -> gtk_types.GLib.Variant:
    error = result.error or ""
    return VariantType("(ass)", (result.items, error))


def _empty_action() -> AnkiActionResult:
    status = AnkiStatus(
        model_status="Model not found",
        deck_status="Not selected",
        deck_name="",
    )
    return AnkiActionResult(message="Invalid request.", status=status)
