import Adw from "gi://Adw";
import Gdk from "gi://Gdk";
import Gio from "gi://Gio";
import GLib from "gi://GLib";
import Gtk from "gi://Gtk";

import { ExtensionPreferences } from "resource:///org/gnome/Shell/Extensions/js/extensions/prefs.js";

const HOTKEY_KEY = "hotkey";
const BUS_NAME = "com.translator.desktop";
const OBJECT_PATH = "/com/translator/desktop";
const INTERFACE_NAME = "com.translator.desktop";
const MESSAGE_TIMEOUT_SECONDS = 2;
let cssApplied = false;

export default class TranslatorPrefs extends ExtensionPreferences {
  fillPreferencesWindow(window) {
    const settings = this.getSettings();

    if (!cssApplied) {
      const cssProvider = new Gtk.CssProvider();
      const css = `
        .translator-anki-row {
          padding-top: 0;
          padding-bottom: 0;
          margin-top: 0;
          margin-bottom: 0;
          min-height: 0;
        }
        .translator-anki-group list,
        .translator-anki-group .list {
          margin: 0;
          padding: 0;
          row-spacing: 0;
        }
        .translator-anki-group row,
        .translator-anki-group .list-row,
        .translator-anki-group .action-row {
          margin: 0;
          padding-top: 0;
          padding-bottom: 0;
          min-height: 0;
        }
      `;
      cssProvider.load_from_data(css, -1);
      Gtk.StyleContext.add_provider_for_display(
        Gdk.Display.get_default(),
        cssProvider,
        Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION,
      );
      cssApplied = true;
    }

    window.set_default_size(520, 420);
    const page = new Adw.PreferencesPage();
    page.set_margin_bottom(0);
    const group = new Adw.PreferencesGroup();
    group.set_margin_bottom(0);
    const row = new Adw.ActionRow({ title: "Hotkey" });
    const valueLabel = new Gtk.Label({ xalign: 0 });
    row.add_suffix(valueLabel);
    row.set_activatable(true);
    row.activatable_widget = valueLabel;
    group.add(row);

    const hotkeyButtonsRow = new Adw.PreferencesRow();
    hotkeyButtonsRow.set_margin_bottom(0);
    const delButton = new Gtk.Button({ label: "Del" });
    const resetButton = new Gtk.Button({ label: "Reset" });
    const hotkeyButtons = new Gtk.Box({
      orientation: Gtk.Orientation.HORIZONTAL,
      spacing: 8,
      homogeneous: true,
      hexpand: true,
    });
    delButton.set_hexpand(true);
    resetButton.set_hexpand(true);
    delButton.set_halign(Gtk.Align.FILL);
    resetButton.set_halign(Gtk.Align.FILL);
    hotkeyButtons.append(delButton);
    hotkeyButtons.append(resetButton);
    hotkeyButtonsRow.set_child(hotkeyButtons);
    group.add(hotkeyButtonsRow);

    page.add(group);

    const ankiGroup = new Adw.PreferencesGroup();
    ankiGroup.add_css_class("translator-anki-group");
    ankiGroup.set_margin_bottom(0);
    const ankiTitleRow = new Adw.PreferencesRow();
    const ankiTitleLabel = new Gtk.Label({ label: "Anki", xalign: 0.5 });
    ankiTitleLabel.set_hexpand(true);
    ankiTitleLabel.set_halign(Gtk.Align.CENTER);
    ankiTitleRow.set_child(ankiTitleLabel);
    ankiGroup.add(ankiTitleRow);
    const createRow = new Adw.ActionRow({ title: "Create model" });
    createRow.add_css_class("translator-anki-row");
    createRow.set_margin_bottom(0);
    const createButton = new Gtk.Button({ hexpand: true });
    const createContent = new Gtk.Box({
      orientation: Gtk.Orientation.HORIZONTAL,
      spacing: 8,
    });
    const createLabel = new Gtk.Label({ label: "Create model", xalign: 0 });
    createLabel.set_hexpand(true);
    const createStatus = new Gtk.Label({ xalign: 1 });
    createContent.append(createLabel);
    createContent.append(createStatus);
    createButton.set_child(createContent);
    createRow.add_suffix(createButton);
    createRow.activatable_widget = createButton;
    ankiGroup.add(createRow);

    const importRow = new Adw.ActionRow({ title: "Import deck" });
    importRow.add_css_class("translator-anki-row");
    importRow.set_margin_top(0);
    const importButton = new Gtk.Button({ hexpand: true });
    const importContent = new Gtk.Box({
      orientation: Gtk.Orientation.HORIZONTAL,
      spacing: 8,
    });
    const importLabel = new Gtk.Label({ label: "Import deck", xalign: 0 });
    importLabel.set_hexpand(true);
    const importStatus = new Gtk.Label({ xalign: 1 });
    importContent.append(importLabel);
    importContent.append(importStatus);
    importButton.set_child(importContent);
    importRow.add_suffix(importButton);
    importRow.activatable_widget = importButton;
    ankiGroup.add(importRow);

    const saveRow = new Adw.PreferencesRow();
    saveRow.set_margin_bottom(0);
    const saveButton = new Gtk.Button({ label: "Save settings", hexpand: true });
    saveButton.set_halign(Gtk.Align.FILL);
    saveRow.set_child(saveButton);
    ankiGroup.add(saveRow);

    page.add(ankiGroup);
    window.add(page);

    const state = {
      capturing: false,
      pending: null,
    };
    const activeCalls = new Set();

    window.connect("close-request", () => {
      for (const cancellable of activeCalls) {
        try {
          cancellable.cancel();
        } catch (error) {}
      }
      activeCalls.clear();
      return false;
    });

    const updateLabel = () => {
      const current = settings.get_strv(HOTKEY_KEY);
      const shown = state.pending ?? (current.length ? current[0] : "");
      valueLabel.set_label(shown);
    };

    updateLabel();
    settings.connect(`changed::${HOTKEY_KEY}`, updateLabel);

    const startCapture = () => {
      state.capturing = true;
      state.pending = null;
      valueLabel.set_label("Press keys...");
    };
    row.connect("activated", startCapture);

    resetButton.connect("clicked", startCapture);

    delButton.connect("clicked", () => {
      settings.set_strv(HOTKEY_KEY, []);
      state.pending = null;
      updateLabel();
      showMessage("Hotkey cleared.");
    });

    const keyController = new Gtk.EventControllerKey();
    keyController.connect("key-pressed", (_ctrl, keyval, _keycode, stateMask) => {
      if (!state.capturing) {
        return Gdk.EVENT_PROPAGATE;
      }
      const accel = Gtk.accelerator_name(keyval, stateMask);
      if (!Gtk.accelerator_valid(keyval, stateMask)) {
        return Gdk.EVENT_STOP;
      }
      state.capturing = false;
      settings.set_strv(HOTKEY_KEY, [accel]);
      state.pending = null;
      updateLabel();
      showMessage("Hotkey updated.");
      return Gdk.EVENT_STOP;
    });
    window.add_controller(keyController);

    const showMessage = (text) => {
      if (!text) {
        return;
      }
      const toast = new Adw.Toast({ title: text });
      toast.set_timeout(MESSAGE_TIMEOUT_SECONDS);
      window.add_toast(toast);
    };

    const updateStatus = (modelStatus, deckStatus, deckName) => {
      const deckText = deckName ? `${deckStatus} (${deckName})` : deckStatus;
      createStatus.set_label(modelStatus);
      importStatus.set_label(deckText);
      createButton.set_sensitive(modelStatus !== "Model ready");
    };

    const callDbus = (method, parameters, onSuccess, onError = null) => {
      const cancellable = new Gio.Cancellable();
      activeCalls.add(cancellable);
      Gio.DBus.session.call(
        BUS_NAME,
        OBJECT_PATH,
        INTERFACE_NAME,
        method,
        parameters,
        null,
        Gio.DBusCallFlags.NONE,
        -1,
        cancellable,
        (conn, res) => {
          activeCalls.delete(cancellable);
          try {
            const value = conn.call_finish(res).deep_unpack();
            onSuccess(value);
          } catch (error) {
            if (onError) {
              onError(error);
            } else {
              const text = error?.message
                ? `D-Bus call failed: ${error.message}`
                : "D-Bus call failed.";
              showMessage(text);
            }
          }
        },
      );
    };

    const refreshStatus = () => {
      callDbus("GetAnkiStatus", null, (value) => {
        const [modelStatus, deckStatus, deckName] = value;
        updateStatus(modelStatus, deckStatus, deckName);
      }, () => {});
    };

    const handleActionResult = (value) => {
      const [message, modelStatus, deckStatus, deckName] = value;
      showMessage(message);
      updateStatus(modelStatus, deckStatus, deckName);
    };

    createButton.connect("clicked", () => {
      callDbus("CreateAnkiModel", null, handleActionResult);
    });

    importButton.connect("clicked", () => {
      callDbus(
        "ListAnkiDecks",
        null,
        (value) => {
          const [decks, error] = value;
          if (error) {
            showMessage(error);
            return;
          }
          if (!decks || !decks.length) {
            showMessage("No Anki decks found.");
            return;
          }
          const dialog = new Adw.MessageDialog({
            transient_for: window,
            modal: true,
            heading: "Select Anki deck",
          });
          const list = new Gtk.StringList();
          decks.forEach((deck) => list.append(deck));
          const dropdown = new Gtk.DropDown({ model: list });
          dialog.set_extra_child(dropdown);
          dialog.add_response("cancel", "Cancel");
          dialog.add_response("select", "Select");
          dialog.set_default_response("select");
          dialog.set_close_response("cancel");
          dialog.connect("response", (_dlg, response) => {
            if (response === "select") {
              const index = dropdown.get_selected();
              if (index >= 0) {
                const deck = list.get_string(index);
                callDbus(
                  "SelectAnkiDeck",
                  new GLib.Variant("(s)", [deck]),
                  handleActionResult,
                );
              }
            }
            dialog.destroy();
          });
          dialog.present();
        },
        (error) => {
          const text = error?.message
            ? `Failed to load decks: ${error.message}`
            : "Failed to load decks.";
          showMessage(text);
        },
      );
    });

    saveButton.connect("clicked", () => {
      callDbus("SaveSettings", null, handleActionResult);
    });

    refreshStatus();
  }
}
