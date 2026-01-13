import Clutter from "gi://Clutter";
import Gio from "gi://Gio";
import GLib from "gi://GLib";
import GObject from "gi://GObject";
import Meta from "gi://Meta";
import Shell from "gi://Shell";
import St from "gi://St";

import * as Main from "resource:///org/gnome/shell/ui/main.js";
import { Extension } from "resource:///org/gnome/shell/extensions/extension.js";
import { Button } from "resource:///org/gnome/shell/ui/panelMenu.js";
import * as PopupMenu from "resource:///org/gnome/shell/ui/popupMenu.js";
import * as Util from "resource:///org/gnome/shell/misc/util.js";

const BUS_NAME = "com.translator.desktop";
const OBJECT_PATH = "/com/translator/desktop";
const INTERFACE_NAME = "com.translator.desktop";
const HOTKEY_SETTING = "hotkey";
const INDICATOR_NAME = "Translator";
const HISTORY_LABEL = "History";
const SETTINGS_LABEL = "Settings";
const DEFAULT_ICON_NAME = "accessories-dictionary-symbolic";
const TEXT_FILTER = /^[.\s\d-]+$/;
const DBUS_RETRY_DELAY_MS = 200;
const DBUS_RETRY_ATTEMPTS = 10;
const DBUS_RETRYABLE_ERRORS = [
  "org.freedesktop.DBus.Error.ServiceUnknown",
  "org.freedesktop.DBus.Error.UnknownObject",
  "org.freedesktop.DBus.Error.UnknownMethod",
];

const TranslatorIndicator = GObject.registerClass(
  class TranslatorIndicator extends Button {
    _init(extension) {
      super._init(0.0, INDICATOR_NAME, false);
      this._extension = extension;
      const icon = new St.Icon({
        style_class: "system-status-icon",
        icon_name: DEFAULT_ICON_NAME,
      });
      const box = new St.BoxLayout({ style_class: "panel-status-menu-box" });
      box.add_child(icon);
      this.add_child(box);

      const historyItem = new PopupMenu.PopupMenuItem(HISTORY_LABEL);
      historyItem.connect("activate", () => {
        this._extension.showHistory();
      });
      this.menu.addMenuItem(historyItem);

      const settingsItem = new PopupMenu.PopupMenuItem(SETTINGS_LABEL);
      settingsItem.connect("activate", () => {
        this._extension.openPreferences();
      });
      this.menu.addMenuItem(settingsItem);
    }
  },
);

export default class TranslatorExtension extends Extension {
  enable() {
    this._settings = this.getSettings();
    this._clipboard = St.Clipboard.get_default();
    this._oldtext = null;
    this._settingsChangedId = this._settings.connect(
      `changed::${HOTKEY_SETTING}`,
      () => {
        this._unregisterHotkey();
        this._registerHotkey();
      },
    );
    this._registerHotkey();
    this._indicator = new TranslatorIndicator(this);
    Main.panel.addToStatusArea(INDICATOR_NAME, this._indicator);
  }

  disable() {
    this._unregisterHotkey();
    if (this._settings && this._settingsChangedId) {
      this._settings.disconnect(this._settingsChangedId);
      this._settingsChangedId = 0;
    }
    if (this._indicator) {
      this._indicator.destroy();
      this._indicator = null;
    }
    this._clipboard = null;
    this._settings = null;
  }

  _registerHotkey() {
    if (!this._settings) {
      return;
    }
    Main.wm.addKeybinding(
      HOTKEY_SETTING,
      this._settings,
      Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
      Shell.ActionMode.ALL,
      this._onHotkey.bind(this),
    );
  }

  _unregisterHotkey() {
    try {
      Main.wm.removeKeybinding(HOTKEY_SETTING);
    } catch (error) {
      logError(error);
    }
  }

  _onHotkey() {
    this._clipboardChanged();
  }

  _clipboardChanged() {
    this._clipboard.get_text(St.ClipboardType.PRIMARY, (_clip, text) => {
      if (
        text &&
        text !== "" &&
        text[0] !== "/" &&
        !Util.findUrls(text).length &&
        !TEXT_FILTER.exec(text)
      ) {
        this._oldtext = text;
        this._callTranslate(text);
      }
    });
  }

  _callTranslate(text) {
    this._callDbus("Translate", new GLib.Variant("(s)", [text]));
  }

  showHistory() {
    this._callDbus("ShowHistory", null);
  }

  _callDbus(method, parameters) {
    this._callDbusWithRetry(method, parameters, 0);
  }

  _callDbusWithRetry(method, parameters, attempt) {
    Gio.DBus.session.call(
      BUS_NAME,
      OBJECT_PATH,
      INTERFACE_NAME,
      method,
      parameters,
      null,
      Gio.DBusCallFlags.NONE,
      -1,
      null,
      (conn, res) => {
        try {
          conn.call_finish(res);
        } catch (error) {
          const message = `${error}`;
          const shouldRetry =
            attempt < DBUS_RETRY_ATTEMPTS &&
            DBUS_RETRYABLE_ERRORS.some((marker) => message.includes(marker));
          if (shouldRetry) {
            GLib.timeout_add(GLib.PRIORITY_DEFAULT, DBUS_RETRY_DELAY_MS, () => {
              this._callDbusWithRetry(method, parameters, attempt + 1);
              return GLib.SOURCE_REMOVE;
            });
            return;
          }
          logError(error);
        }
      },
    );
  }
}
