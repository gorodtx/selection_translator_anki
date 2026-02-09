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
const MAX_TEXT_LEN = 200;
const HOTKEY_DEBOUNCE_MS = 80;
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
    this._proxy = null;
    this._hotkeyDebounceId = 0;
    this._pendingText = null;
    this._hotkey = this._getHotkeyValue();
    this._hotkeyRegistered = false;
    this._settingsChangedId = this._settings.connect(
      `changed::${HOTKEY_SETTING}`,
      () => {
        this._onHotkeyChanged();
      },
    );
    this._registerHotkey();
    this._indicator = new TranslatorIndicator(this);
    Main.panel.addToStatusArea(INDICATOR_NAME, this._indicator);
  }

  disable() {
    this._unregisterHotkey();
    this._clearDebounce();
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
    this._proxy = null;
    this._hotkey = "";
    this._hotkeyRegistered = false;
  }

  _getHotkeyValue() {
    if (!this._settings) {
      return "";
    }
    const values = this._settings.get_strv(HOTKEY_SETTING);
    return values.length ? values[0] : "";
  }

  _onHotkeyChanged() {
    const next = this._getHotkeyValue();
    if (next === this._hotkey) {
      return;
    }
    this._hotkey = next;
    this._unregisterHotkey();
    this._registerHotkey();
  }

  _registerHotkey() {
    if (!this._settings) {
      return;
    }
    const current = this._getHotkeyValue();
    if (!current) {
      return;
    }
    Main.wm.addKeybinding(
      HOTKEY_SETTING,
      this._settings,
      Meta.KeyBindingFlags.IGNORE_AUTOREPEAT,
      Shell.ActionMode.ALL,
      this._onHotkey.bind(this),
    );
    this._hotkeyRegistered = true;
  }

  _unregisterHotkey() {
    if (!this._hotkeyRegistered) {
      return;
    }
    try {
      Main.wm.removeKeybinding(HOTKEY_SETTING);
    } catch (error) {}
    this._hotkeyRegistered = false;
  }

  _onHotkey() {
    this._clipboardChanged();
  }

  _clipboardChanged() {
    this._clipboard.get_text(St.ClipboardType.PRIMARY, (_clip, text) => {
      const candidate = this._sanitizeText(text);
      if (!candidate) {
        return;
      }
      this._oldtext = candidate;
      this._scheduleTranslate(candidate);
    });
  }

  _sanitizeText(text) {
    if (!text) {
      return null;
    }
    let trimmed = text;
    if (trimmed.length > MAX_TEXT_LEN) {
      trimmed = trimmed.slice(0, MAX_TEXT_LEN);
    }
    if (
      !trimmed ||
      trimmed === "" ||
      trimmed[0] === "/" ||
      Util.findUrls(trimmed).length ||
      TEXT_FILTER.exec(trimmed)
    ) {
      return null;
    }
    return trimmed;
  }

  _scheduleTranslate(text) {
    this._pendingText = text;
    if (this._hotkeyDebounceId !== 0) {
      return;
    }
    this._hotkeyDebounceId = GLib.timeout_add(
      GLib.PRIORITY_DEFAULT,
      HOTKEY_DEBOUNCE_MS,
      () => {
        this._hotkeyDebounceId = 0;
        const pending = this._pendingText;
        this._pendingText = null;
        if (pending) {
          this._callTranslate(pending);
        }
        return GLib.SOURCE_REMOVE;
      },
    );
  }

  _clearDebounce() {
    if (this._hotkeyDebounceId === 0) {
      return;
    }
    GLib.source_remove(this._hotkeyDebounceId);
    this._hotkeyDebounceId = 0;
    this._pendingText = null;
  }

  _callTranslate(text) {
    this._callDbus("Translate", new GLib.Variant("(s)", [text]));
  }

  showHistory() {
    this._callDbus("ShowHistory", null);
  }

  _getProxy() {
    if (this._proxy) {
      return this._proxy;
    }
    try {
      this._proxy = Gio.DBusProxy.new_for_bus_sync(
        Gio.BusType.SESSION,
        Gio.DBusProxyFlags.NONE,
        null,
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE_NAME,
        null,
      );
    } catch (error) {
      this._proxy = null;
    }
    return this._proxy;
  }

  _callDbus(method, parameters) {
    this._callDbusWithRetry(method, parameters, 0);
  }

  _callDbusWithRetry(method, parameters, attempt) {
    const proxy = this._getProxy();
    if (!proxy) {
      this._scheduleRetry(method, parameters, attempt);
      return;
    }
    proxy.call(
      method,
      parameters,
      Gio.DBusCallFlags.NONE,
      -1,
      null,
      (activeProxy, res) => {
        try {
          activeProxy.call_finish(res);
        } catch (error) {
          const message = `${error}`;
          const shouldRetry =
            attempt < DBUS_RETRY_ATTEMPTS &&
            DBUS_RETRYABLE_ERRORS.some((marker) => message.includes(marker));
          if (shouldRetry) {
            this._proxy = null;
            this._scheduleRetry(method, parameters, attempt);
            return;
          }
          return;
        }
      },
    );
  }

  _scheduleRetry(method, parameters, attempt) {
    if (attempt >= DBUS_RETRY_ATTEMPTS) {
      return;
    }
    GLib.timeout_add(GLib.PRIORITY_DEFAULT, DBUS_RETRY_DELAY_MS, () => {
      this._callDbusWithRetry(method, parameters, attempt + 1);
      return GLib.SOURCE_REMOVE;
    });
  }
}
