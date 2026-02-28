<div align="center">
  <img src="icons/main_icon.png" width="180" alt="Translator icon" />
</div>

<h1 align="center">Translator for GNOME</h1>

<h4 align="center">
Offline-first selection translator for Linux GNOME with fast popup UI, D-Bus backend, and Anki integration.
</h4>

<div align="center">
  <a href="https://github.com/gorodtx/selection_translator_anki/releases/latest"><b>🟢 Install for Linux GNOME</b></a> •
  <a href="https://github.com/gorodtx/selection_translator_anki/releases/latest"><b>📦 Releases</b></a> •
  <a href="scripts/install.sh"><b>🛠️ Installer Script</b></a> •
  <a href="dev/"><b>🧪 Dev Tools (optional)</b></a>
</div>

<br/>

[English](#english) | [Русский](#русский)

Supported now: **Linux GNOME (Wayland/X11)**.  
In progress: **Windows prep (no production adapter yet)**.  
Out of scope for current cycle: **macOS**.

[![Python](https://img.shields.io/badge/Python-3.13-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![GTK4](https://img.shields.io/badge/GTK-4-7FE719?logo=gtk&logoColor=black)](https://www.gtk.org/)
[![GNOME Shell](https://img.shields.io/badge/GNOME-Shell-4A86CF?logo=gnome&logoColor=white)](https://www.gnome.org/)
[![D-Bus](https://img.shields.io/badge/D--Bus-IPC-6B7280)](https://www.freedesktop.org/wiki/Software/dbus/)
[![aiohttp](https://img.shields.io/badge/aiohttp-async%20http-2C5BB4)](https://docs.aiohttp.org/)
[![GitHub Release](https://img.shields.io/github/v/release/gorodtx/selection_translator_anki?label=Release)](https://github.com/gorodtx/selection_translator_anki/releases/latest)
[![Platform](https://img.shields.io/badge/Platform-Linux%20GNOME-2ea44f)](https://github.com/gorodtx/selection_translator_anki/releases/latest)
[![CI Matrix](https://img.shields.io/badge/CI-matrix%20(3%20OS)-0a66c2)](.github/workflows/ci-matrix.yml)
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

### 3) Platform architecture (current)

- `core`: translation flow, contracts, cache, history.
- `linux-gnome adapter`: GNOME extension + D-Bus + GTK runtime.
- `windows adapter`: prep contract only (not enabled in production).
- `mac adapter`: prep stub only (not enabled in production).

### 4) Runtime and installer contract

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

### 5) Troubleshooting

- Extension not visible after install:
  - log out and log in again, then run `gnome-extensions enable translator@com.translator.desktop`.
- Service status:
  - `systemctl --user status translator-desktop.service`
- Runtime logs:
  - `journalctl --user -u translator-desktop.service -n 200 --no-pager`
- If hotkey does nothing:
  - run installer healthcheck, then re-run `install` or `update`.

### 6) Release flow (maintainers)

Release guardrails (hard fail by default):
- Build only from a clean tracked git state (no unstaged/staged tracked changes).
- `translator-app.tar.gz` is created from `git archive HEAD` (tracked files only).
- `.sqlite3` inside app archive is blocked; offline DB ships only as separate release assets.
- Immutable release policy: existing tag/release must not be modified.
- Optional override for emergency/debug only: `TRANSLATOR_RELEASE_ALLOW_DIRTY=1`.
- Channel policy:
  - `vX.Y.Z-rc.N` for cross-platform matrix rehearsal.
  - `vX.Y.Z` only after green matrix and Linux production gate.

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
Windows VM gate runbook: `docs/windows/vm-gate.md`.
Windows VM options fact-check: `docs/windows/vm-options-fact-check.md`.
Windows VM checklist template: `docs/windows/vm-gate-checklist.md`.

Parallel stable+dev runtime runbook: `dev/docs/parallel_runtime.md`.

Dev isolation bootstrap (from stable checkout):

```bash
# creates ~/dev/translator-dev and moves local dirty changes there
dev/scripts/bootstrap_dev_worktree.sh ~/dev/translator-dev
```

Dev runtime control (inside dev worktree):

```bash
cd ~/dev/translator-dev
dev/run_dev_instance.sh setup
dev/run_dev_instance.sh sync-bases
dev/run_dev_instance.sh status
dev/run_dev_instance.sh switch-to-dev
```

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

### 3) Платформенная архитектура (текущее состояние)

- `core`: translation flow, контракты, кэш, история.
- `linux-gnome adapter`: GNOME extension + D-Bus + GTK runtime.
- `windows adapter`: только prep-контракт (в production не включён).
- `mac adapter`: только prep-stub (в production не включён).

### 4) Контракт рантайма и инсталлятора

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

### 5) Troubleshooting / Диагностика

- После установки extension не появился:
  - сделай logout/login, затем `gnome-extensions enable translator@com.translator.desktop`.
- Статус сервиса:
  - `systemctl --user status translator-desktop.service`
- Логи рантайма:
  - `journalctl --user -u translator-desktop.service -n 200 --no-pager`
- Хоткей не срабатывает:
  - запусти healthcheck инсталлятора, затем повтори `install` или `update`.

### 6) Релизный цикл (для мейнтейнеров)

Защита релиза (по умолчанию жёсткий fail):
- Сборка только из чистого tracked-состояния git (без staged/unstaged tracked-изменений).
- `translator-app.tar.gz` собирается через `git archive HEAD` (только tracked файлы).
- `.sqlite3` внутри app-архива запрещены; офлайн-базы идут только отдельными release-ассетами.
- Immutable policy: уже опубликованный тег/релиз не изменяется.
- Обход только для аварий/дебага: `TRANSLATOR_RELEASE_ALLOW_DIRTY=1`.
- Политика каналов:
  - `vX.Y.Z-rc.N` для кроссплатформенного прогона matrix.
  - `vX.Y.Z` только после зелёной matrix и Linux production gate.

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
Runbook Windows VM gate: `docs/windows/vm-gate.md`.
Факт-чек и сравнение вариантов VM: `docs/windows/vm-options-fact-check.md`.
Шаблон чеклиста Windows VM: `docs/windows/vm-gate-checklist.md`.

Runbook параллельного stable+dev режима: `dev/docs/parallel_runtime.md`.

Bootstrap из stable checkout для dev-изоляции:

```bash
# создаёт ~/dev/translator-dev и переносит туда текущий dirty state
dev/scripts/bootstrap_dev_worktree.sh ~/dev/translator-dev
```

Управление dev-рантаймом (внутри dev worktree):

```bash
cd ~/dev/translator-dev
dev/run_dev_instance.sh setup
dev/run_dev_instance.sh sync-bases
dev/run_dev_instance.sh status
dev/run_dev_instance.sh switch-to-dev
```

## License

MIT — see [LICENSE](LICENSE).
