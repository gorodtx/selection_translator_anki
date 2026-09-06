<div align="center">
  <img src="icons/main_icon.png" width="180" alt="Translator icon" />
</div>

<h1 align="center">Translator</h1>

<h4 align="center">
Offline-first selection translator with a fast popup UI and Anki integration.<br/>
Linux GNOME (GTK4 + D-Bus) and macOS (SwiftUI + Unix socket) share one translation engine.
</h4>

<div align="center">
  <a href="https://github.com/gorodtx/selection_translator_anki/releases/latest"><b>🟢 Install for Linux GNOME</b></a> •
  <a href="https://github.com/gorodtx/selection_translator_anki/releases/latest"><b>📦 Releases</b></a> •
  <a href="scripts/install.sh"><b>🛠️ Installer Script</b></a> •
  <a href="dev/"><b>🧪 Dev Tools (optional)</b></a>
</div>

<br/>

[English](#english) | [Русский](#русский)

Supported now: **Linux GNOME (Wayland/X11)** and **macOS 26 (Apple silicon)**.  
Planned (not supported yet): **Windows**.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GTK4](https://img.shields.io/badge/GTK-4-7FE719?logo=gtk&logoColor=black)](https://www.gtk.org/)
[![GNOME Shell](https://img.shields.io/badge/GNOME-Shell-4A86CF?logo=gnome&logoColor=white)](https://www.gnome.org/)
[![D-Bus](https://img.shields.io/badge/D--Bus-IPC-6B7280)](https://www.freedesktop.org/wiki/Software/dbus/)
[![aiohttp](https://img.shields.io/badge/aiohttp-async%20http-2C5BB4)](https://docs.aiohttp.org/)
[![GitHub Release](https://img.shields.io/github/v/release/gorodtx/selection_translator_anki?label=Release)](https://github.com/gorodtx/selection_translator_anki/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Linux%20GNOME-2ea44f)](https://github.com/gorodtx/selection_translator_anki/releases/latest)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)

## Quick Install / Быстрая установка

Release / Релиз: <https://github.com/gorodtx/selection_translator_anki/releases/latest>

Install latest stable release:

```bash
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- install
```

Pin install to an exact tag (`vX.Y.Z`):

```bash
TRANSLATOR_RELEASE_TAG=vX.Y.Z \
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- install
```

Update / remove / rollback / healthcheck:

```bash
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- update
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- remove
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- rollback
curl -fsSL https://github.com/gorodtx/selection_translator_anki/releases/latest/download/install.sh | bash -s -- healthcheck
```

Smoke checks:

```bash
gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "hello"
gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.Translate "look up"
gdbus call --session --dest com.translator.desktop --object-path /com/translator/desktop --method com.translator.desktop.GetAnkiStatus
```

---

## English

### 1) What this project gives you

- GNOME hotkey translation from primary selection.
- Fast two-phase UI: partial result first, then final result.
- Offline language bases for examples and definitions.
- Runtime + extension wiring via user-level systemd and D-Bus.
- Anki actions from the translation popup and settings flow.

### 2) How it works

1. GNOME Shell extension captures hotkey and selected text.
2. Extension calls D-Bus service `com.translator.desktop`.
3. Python backend runs translation pipeline and updates GTK window.
4. Results are cached and stored for history reuse.

### 3) Runtime and installer contract

- Installer deploys:
  - app runtime (`translator-app.tar.gz`)
  - extension (`translator-extension.zip`)
  - offline bases (`primary.sqlite3`, `fallback.sqlite3`, `definitions_pack.sqlite3`)
- `release-assets.sha256` is mandatory; all assets are checksum-verified.
- Runtime service is managed by user systemd: `translator-desktop.service`.
- Installer keeps `current` + `previous` releases and prunes older ones.

Install from repository checkout:

```bash
bash scripts/install.sh install
bash scripts/install.sh update
bash scripts/install.sh rollback
bash scripts/install.sh remove
bash scripts/install.sh healthcheck
```

### 3a) macOS

The engine is not forked per platform: `translate_logic` and `desktop_app/application`
are shared, and only the adapter differs — GTK4 + D-Bus on GNOME,
a SwiftUI shell talking to a Unix-socket backend daemon on macOS.

Build and install from a checkout. Xcode is not required; Command Line Tools are enough:

```bash
scripts/build_macos_app.sh          # -> dist/Translator.app (~55 MB)
scripts/install_macos.sh install    # -> ~/Applications + launchd agent + offline bases
scripts/install_macos.sh healthcheck
scripts/install_macos.sh rollback
scripts/install_macos.sh remove
```

The bundle carries a relocatable CPython 3.13, the backend sources and the
`apple-lang-helper` sidecar. The 1.8 GB offline bases are **never** shipped inside it:
`install_macos.sh` downloads them into `~/Library/Application Support/Translator/db`
and verifies every file against `scripts/db-bundle.lock.json`.

Run the backend from the checkout during development:

```bash
scripts/run_backend_macos.sh
uv run python -m desktop_app.platform.macos.client ping
uv run python -m desktop_app.platform.macos.client translate '{"text": "look up"}'
```

Paths (override with `TRANSLATOR_CONFIG_DIR`, `TRANSLATOR_DB_DIR`,
`TRANSLATOR_SOCKET_PATH`, `TRANSLATOR_LOG_DIR`):

| What | Where |
| --- | --- |
| config | `~/Library/Application Support/Translator/desktop_config.json` |
| offline bases | `~/Library/Application Support/Translator/db` |
| backend socket | `~/Library/Application Support/Translator/run/backend.sock` |
| logs | `~/Library/Logs/Translator/backend.log` |

**Apple on-device engines.** On macOS the pipeline also queries Dictionary Services —
the Oxford Russian Dictionary behind system Look Up — and, when the language pair is
installed, `Translation.framework`. The dictionary answers in about a millisecond and
supplies the first partial result, IPA and sense-numbered translations while the network
providers are still in flight. Install the en→ru pair in System Settings → General →
Language & Region → Translation Languages; without it the machine-translation half
degrades silently and everything else keeps working.

### 4) Troubleshooting

- Extension not visible after install:
  - log out and log in again, then run `gnome-extensions enable translator@com.translator.desktop`.
- Service status:
  - `systemctl --user status translator-desktop.service`
- Runtime logs:
  - `journalctl --user -u translator-desktop.service -n 200 --no-pager`
- If hotkey does nothing:
  - run installer healthcheck, then re-run `install` or `update`.

### 5) Release flow (maintainers)

Release guardrails (hard fail by default):
- Build only from a clean tracked git state (no unstaged/staged tracked changes).
- `translator-app.tar.gz` is created from `git archive HEAD` (tracked files only).
- `.sqlite3` inside app archive is blocked; offline DB ships only as separate release assets.
- Immutable policy: existing tag/release must not be modified.
- Optional override for emergency/debug only: `TRANSLATOR_RELEASE_ALLOW_DIRTY=1`.

```bash
dev/scripts/release_preflight.sh vX.Y.Z
```

```bash
git push origin main
git tag vX.Y.Z
git push origin vX.Y.Z
```

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --generate-notes \
  dev/dist/release/install.sh \
  dev/dist/release/assets/release-assets.sha256 \
  dev/dist/release/assets/translator-app.tar.gz \
  dev/dist/release/assets/translator-extension.zip \
  dev/dist/release/assets/primary.sqlite3 \
  dev/dist/release/assets/fallback.sqlite3 \
  dev/dist/release/assets/definitions_pack.sqlite3
```

Detailed gate checklist: `dev/docs/release_gate.md`.

---

## Русский

### 1) Что даёт проект

- Перевод выделенного текста по хоткею в GNOME.
- Быстрый двухэтапный UI: сначала partial, потом final.
- Офлайн-базы для примеров и определений.
- Связка расширения и backend через user systemd + D-Bus.
- Интеграция с Anki из окна перевода и настроек.

### 2) Как это работает

1. GNOME extension ловит хоткей и читает выделение.
2. Extension вызывает D-Bus сервис `com.translator.desktop`.
3. Python backend запускает pipeline перевода и обновляет GTK-окно.
4. Результаты кэшируются и сохраняются в историю.

### 3) Контракт рантайма и инсталлятора

- Инсталлятор ставит:
  - runtime приложения (`translator-app.tar.gz`)
  - extension (`translator-extension.zip`)
  - офлайн-базы (`primary.sqlite3`, `fallback.sqlite3`, `definitions_pack.sqlite3`)
- `release-assets.sha256` обязателен; все ассеты проверяются по checksum.
- Сервис рантайма: `translator-desktop.service` (user-level systemd).
- Хранятся `current` и `previous` релизы; старые релизы чистятся автоматически.

Установка из checkout репозитория:

```bash
bash scripts/install.sh install
bash scripts/install.sh update
bash scripts/install.sh rollback
bash scripts/install.sh remove
bash scripts/install.sh healthcheck
```

### 3a) macOS

Движок не форкается по платформам: `translate_logic` и `desktop_app/application` общие,
различается только адаптер — GTK4 + D-Bus в GNOME и оболочка SwiftUI поверх демона
на unix-сокете в macOS.

Сборка и установка из checkout. Xcode не нужен, достаточно Command Line Tools:

```bash
scripts/build_macos_app.sh          # -> dist/Translator.app (~55 МБ)
scripts/install_macos.sh install    # -> ~/Applications + launchd-агент + офлайн-базы
scripts/install_macos.sh healthcheck
scripts/install_macos.sh rollback
scripts/install_macos.sh remove
```

В бандле лежат релокейтабельный CPython 3.13, исходники бэкенда и сайдкар
`apple-lang-helper`. Офлайн-базы на 1.8 ГБ внутрь **никогда** не кладутся:
`install_macos.sh` качает их в `~/Library/Application Support/Translator/db`
и сверяет каждый файл с `scripts/db-bundle.lock.json`.

Запуск бэкенда из репозитория при разработке:

```bash
scripts/run_backend_macos.sh
uv run python -m desktop_app.platform.macos.client ping
uv run python -m desktop_app.platform.macos.client translate '{"text": "look up"}'
```

Пути (переопределяются через `TRANSLATOR_CONFIG_DIR`, `TRANSLATOR_DB_DIR`,
`TRANSLATOR_SOCKET_PATH`, `TRANSLATOR_LOG_DIR`):

| Что | Где |
| --- | --- |
| конфиг | `~/Library/Application Support/Translator/desktop_config.json` |
| офлайн-базы | `~/Library/Application Support/Translator/db` |
| сокет бэкенда | `~/Library/Application Support/Translator/run/backend.sock` |
| логи | `~/Library/Logs/Translator/backend.log` |

**Системные движки Apple.** На macOS пайплайн дополнительно спрашивает Dictionary
Services — тот самый Oxford Russian Dictionary, который показывает системный Look Up, —
и `Translation.framework`, когда языковая пара установлена. Словарь отвечает примерно
за миллисекунду и отдаёт первый частичный результат, транскрипцию и переводы по
значениям, пока сетевые провайдеры ещё в пути. Пару en→ru ставят в Системных
настройках → Основные → Язык и регион → Языки перевода; без неё машинный перевод
тихо отключается, всё остальное работает.

### 4) Troubleshooting / Диагностика

- После установки extension не появился:
  - сделай logout/login, затем `gnome-extensions enable translator@com.translator.desktop`.
- Статус сервиса:
  - `systemctl --user status translator-desktop.service`
- Логи рантайма:
  - `journalctl --user -u translator-desktop.service -n 200 --no-pager`
- Хоткей не срабатывает:
  - запусти healthcheck инсталлятора, затем повтори `install` или `update`.

### 5) Релизный цикл (для мейнтейнеров)

Защита релиза (по умолчанию жёсткий fail):
- Сборка только из чистого tracked-состояния git (без staged/unstaged tracked-изменений).
- `translator-app.tar.gz` собирается через `git archive HEAD` (только tracked файлы).
- `.sqlite3` внутри app-архива запрещены; офлайн-базы идут только отдельными release-ассетами.
- Immutable policy: уже опубликованный тег/релиз не изменяется.
- Обход только для аварий/дебага: `TRANSLATOR_RELEASE_ALLOW_DIRTY=1`.

```bash
dev/scripts/release_preflight.sh vX.Y.Z
```

```bash
git push origin main
git tag vX.Y.Z
git push origin vX.Y.Z
```

```bash
gh release create vX.Y.Z \
  --title "vX.Y.Z" \
  --generate-notes \
  dev/dist/release/install.sh \
  dev/dist/release/assets/release-assets.sha256 \
  dev/dist/release/assets/translator-app.tar.gz \
  dev/dist/release/assets/translator-extension.zip \
  dev/dist/release/assets/primary.sqlite3 \
  dev/dist/release/assets/fallback.sqlite3 \
  dev/dist/release/assets/definitions_pack.sqlite3
```

Полный gate-чеклист: `dev/docs/release_gate.md`.

## License

MIT — see [LICENSE](LICENSE).
