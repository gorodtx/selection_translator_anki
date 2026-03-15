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
const DBUS_RETRY_ATTEMPTS = 40;
const DBUS_RETRY_DELAY_MS = 100;
const MAX_TEXT_LEN = 200;
const TRANSLATE_REQUEST_KEY = "translate";
const HISTORY_REQUEST_KEY = "show-history";
const DBUS_RETRYABLE_ERRORS = [
  "org.freedesktop.DBus.Error.ServiceUnknown",
  "org.freedesktop.DBus.Error.UnknownObject",
  "org.freedesktop.DBus.Error.UnknownMethod",
  "org.freedesktop.DBus.Error.NoReply",
  "org.freedesktop.DBus.Error.Timeout",
  "org.freedesktop.DBus.Error.TimedOut",
  "Gio.IOErrorEnum.TimedOut",
  "Gio.IOErrorEnum.Cancelled",
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
    this._enabled = true;
    this._settings = this.getSettings();
    this._clipboard = St.Clipboard.get_default();
    this._oldtext = null;
    this._proxy = null;
    this._proxyLoading = false;
    this._proxyWaiters = [];
    this._proxyInitCancellable = null;
    this._dbusRequests = new Map();
    this._requestSequence = 0;
    this._captureGeneration = 0;
    this._captureId = 0;
    this._activeCapture = null;
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
    this._enabled = false;
    this._unregisterHotkey();
    if (this._settings && this._settingsChangedId) {
      this._settings.disconnect(this._settingsChangedId);
      this._settingsChangedId = 0;
    }
    if (this._indicator) {
      this._indicator.destroy();
      this._indicator = null;
    }
    this._cancelAllDbusRequests();
    this._cancelProxyInitialization();
    this._clipboard = null;
    this._settings = null;
    this._proxy = null;
    this._proxyLoading = false;
    this._proxyWaiters = [];
    this._proxyInitCancellable = null;
    this._dbusRequests = null;
    this._requestSequence = 0;
    this._captureGeneration = 0;
    this._captureId = 0;
    this._activeCapture = null;
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
    if (!this._clipboard) {
      return;
    }
    const capture = this._beginCapture();
    this._clipboard.get_text(St.ClipboardType.PRIMARY, (_clip, text) => {
      if (!this._isCaptureActive(capture)) {
        return;
      }
      const candidate = this._sanitizeText(text);
      if (!candidate) {
        return;
      }
      this._oldtext = candidate;
      this._callTranslate(candidate, capture);
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

  _beginCapture() {
    this._captureGeneration += 1;
    this._captureId += 1;
    const capture = {
      generation: this._captureGeneration,
      captureId: this._captureId,
    };
    this._activeCapture = capture;
    this._cancelDbusRequest(TRANSLATE_REQUEST_KEY);
    return capture;
  }

  _isCaptureActive(capture) {
    return (
      this._enabled &&
      capture != null &&
      this._activeCapture != null &&
      capture.generation === this._activeCapture.generation &&
      capture.captureId === this._activeCapture.captureId
    );
  }

  _callTranslate(text, capture) {
    this._callDbus("Translate", new GLib.Variant("(s)", [text]), {
      requestKey: TRANSLATE_REQUEST_KEY,
      staleCheck: () => this._isCaptureActive(capture),
    });
  }

  showHistory() {
    this._callDbus("ShowHistory", null, {
      requestKey: HISTORY_REQUEST_KEY,
    });
  }

  _ensureProxy(callback) {
    if (this._proxy) {
      callback(this._proxy);
      return;
    }
    this._proxyWaiters.push(callback);
    if (this._proxyLoading) {
      return;
    }
    this._proxyLoading = true;
    const cancellable = new Gio.Cancellable();
    this._proxyInitCancellable = cancellable;
    Gio.DBusProxy.new_for_bus(
      Gio.BusType.SESSION,
      Gio.DBusProxyFlags.NONE,
      null,
      BUS_NAME,
      OBJECT_PATH,
      INTERFACE_NAME,
      cancellable,
      (_source, res) => {
        const waiters = this._proxyWaiters;
        this._proxyWaiters = [];
        this._proxyLoading = false;
        if (this._proxyInitCancellable === cancellable) {
          this._proxyInitCancellable = null;
        }
        let proxy = null;
        try {
          proxy = Gio.DBusProxy.new_for_bus_finish(res);
          this._proxy = proxy;
        } catch (error) {
          this._proxy = null;
        }
        for (const waiter of waiters) {
          try {
            waiter(proxy);
          } catch (error) {}
        }
      },
    );
  }

  _cancelProxyInitialization() {
    if (this._proxyInitCancellable) {
      try {
        this._proxyInitCancellable.cancel();
      } catch (error) {}
      this._proxyInitCancellable = null;
    }
  }

  _nextRequest(method, parameters, options = {}) {
    const requestKey =
      options.requestKey ?? `${method}:${this._requestSequence + 1}`;
    this._cancelDbusRequest(requestKey);
    const request = {
      requestKey,
      method,
      parameters,
      sequence: ++this._requestSequence,
      staleCheck: options.staleCheck ?? (() => this._enabled),
      retrySourceId: 0,
      cancellable: null,
    };
    this._dbusRequests.set(requestKey, request);
    return request;
  }

  _isRequestActive(request) {
    if (!this._enabled || !request || !this._dbusRequests) {
      return false;
    }
    if (!request.staleCheck()) {
      return false;
    }
    const activeRequest = this._dbusRequests.get(request.requestKey);
    return (
      activeRequest != null && activeRequest.sequence === request.sequence
    );
  }

  _clearRetrySource(request) {
    if (!request || !request.retrySourceId) {
      return;
    }
    try {
      GLib.source_remove(request.retrySourceId);
    } catch (error) {}
    request.retrySourceId = 0;
  }

  _clearCancellable(request, cancel = false) {
    if (!request || !request.cancellable) {
      return;
    }
    if (cancel) {
      try {
        request.cancellable.cancel();
      } catch (error) {}
    }
    request.cancellable = null;
  }

  _finishDbusRequest(request) {
    if (!request || !this._dbusRequests) {
      return;
    }
    const activeRequest = this._dbusRequests.get(request.requestKey);
    if (!activeRequest || activeRequest.sequence !== request.sequence) {
      return;
    }
    this._clearRetrySource(request);
    this._clearCancellable(request);
    this._dbusRequests.delete(request.requestKey);
  }

  _cancelDbusRequest(requestKey) {
    if (!this._dbusRequests) {
      return;
    }
    const request = this._dbusRequests.get(requestKey);
    if (!request) {
      return;
    }
    this._clearRetrySource(request);
    this._clearCancellable(request, true);
    this._dbusRequests.delete(requestKey);
  }

  _cancelAllDbusRequests() {
    if (!this._dbusRequests) {
      return;
    }
    for (const requestKey of Array.from(this._dbusRequests.keys())) {
      this._cancelDbusRequest(requestKey);
    }
  }

  _scheduleRetry(request, nextAttempt) {
    if (!this._isRequestActive(request)) {
      this._finishDbusRequest(request);
      return;
    }
    this._clearRetrySource(request);
    request.retrySourceId = GLib.timeout_add(
      GLib.PRIORITY_DEFAULT,
      DBUS_RETRY_DELAY_MS,
      () => {
        request.retrySourceId = 0;
        if (!this._isRequestActive(request)) {
          this._finishDbusRequest(request);
          return GLib.SOURCE_REMOVE;
        }
        this._callDbusWithRetry(request, nextAttempt);
        return GLib.SOURCE_REMOVE;
      },
    );
  }

  _callDbus(method, parameters, options = {}) {
    const request = this._nextRequest(method, parameters, options);
    this._callDbusWithRetry(request, 0);
  }

  _callDbusWithRetry(request, attempt) {
    if (!this._isRequestActive(request)) {
      this._finishDbusRequest(request);
      return;
    }
    this._ensureProxy((proxy) => {
      if (!this._isRequestActive(request)) {
        this._finishDbusRequest(request);
        return;
      }
      if (!proxy) {
        if (attempt < DBUS_RETRY_ATTEMPTS) {
          this._scheduleRetry(request, attempt + 1);
        } else {
          this._finishDbusRequest(request);
        }
        return;
      }
      const cancellable = new Gio.Cancellable();
      request.cancellable = cancellable;
      proxy.call(
        request.method,
        request.parameters,
        Gio.DBusCallFlags.NONE,
        -1,
        cancellable,
        (activeProxy, res) => {
          if (request.cancellable === cancellable) {
            request.cancellable = null;
          }
          if (!this._isRequestActive(request)) {
            this._finishDbusRequest(request);
            return;
          }
          try {
            activeProxy.call_finish(res);
            this._finishDbusRequest(request);
          } catch (error) {
            const message = `${error}`;
            const shouldRetry =
              attempt < DBUS_RETRY_ATTEMPTS &&
              DBUS_RETRYABLE_ERRORS.some((marker) => message.includes(marker));
            if (shouldRetry) {
              this._proxy = null;
              this._scheduleRetry(request, attempt + 1);
              return;
            }
            this._finishDbusRequest(request);
          }
        },
      );
    });
  }
}
