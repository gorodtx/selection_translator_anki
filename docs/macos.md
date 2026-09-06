# macOS port

Reference for the macOS adapter: what runs where, how the pieces talk, and what
has actually been verified on hardware.

## Processes

```
 selection / hotkey / Services
            │
            ▼
   Translator.app  (SwiftUI shell, LSUIElement)
            │  Unix domain socket, NDJSON
            ▼
   backend daemon  (embedded CPython 3.13)
       ├── translate_logic pipeline  ── network: Google, Cambridge
       │                             ── offline SQLite: primary / fallback / definitions
       └── apple-lang-helper  (Swift sidecar, stdio NDJSON)
                ├── Dictionary Services  (Oxford Russian Dictionary)
                └── Translation.framework
```

The shell owns input, presentation and the pasteboard. The daemon owns the
translation pipeline, history, cache and Anki. Nothing under
`desktop_app/presentation` (GTK) is imported by the daemon.

## Backend protocol

`desktop_app/platform/macos/ipc/protocol.py` is the single source of truth. One
JSON object per line, UTF-8.

| Direction | Shape |
| --- | --- |
| request | `{"id": <str\|int>, "method": "...", "params": {...}}` |
| response | `{"id": ..., "ok": true, "result": {...}}` or `{"id": ..., "ok": false, "error": {"code","message"}}` |
| event | `{"event": "...", "payload": {...}}` (no `id`) |

Methods: `ping`, `translate`, `cancel`, `close`, `history.list`,
`history.select`, `examples.refresh`, `copy_all`, `anki.status`, `anki.decks`,
`anki.select_deck`, `anki.create_model`, `anki.prepare_upsert`,
`anki.apply_upsert`, `settings.get`, `settings.save`, `shutdown`.

Events: `translation.state` (phases `begin`/`partial`/`final`/`error`/`examples`),
`notification`, `anki.availability`.

The view state carries both `translation` (hard-wrapped for the GTK label, kept
for parity) and `translation_raw` (unwrapped — native clients should use this),
plus `apple`: the `LexicalInfo` tree with IPA, parts of speech and
sense-numbered translations when the dictionary matched.

Socket path: `~/Library/Application Support/Translator/run/backend.sock`.
**AF_UNIX allows at most 103 bytes**; the daemon refuses a longer path with a
clear error instead of failing inside `bind()`.

## Sidecar protocol

`macos/AppleLangHelper` speaks NDJSON on stdio; the Python client is
`translate_logic/infrastructure/providers/apple.py`, which keeps one long-lived
process per event loop and re-spawns it up to three times if it exits.

Ops: `ping`, `dictionaries`, `availability`, `define`, `text_definition`,
`translate`, `shutdown`.

`define` answers with records (`dictionary`, `headword`, `title`, `anchor`,
`markup`). When `markup` is present the client hands the records to
`translate_logic.infrastructure.providers.apple_dcs` for structured parsing;
otherwise it falls back to `text_definition` and parses the flat
`DCSCopyTextDefinition` string itself. Both paths end in the same `LexicalInfo`.

Translation errors are typed: `translation_not_installed`,
`translation_unsupported`, `translation_failed`, `unsupported_os`. All of them
mean "no machine translation" to the pipeline — never a hard failure.

## How the Apple engines join the pipeline

`translate_logic/application/pipeline/translate.py` races the on-device lookup
against the network providers:

1. The dictionary lookup starts in parallel with Google and Cambridge.
2. Whichever produces a usable translation first becomes the partial result.
3. The final result merges Apple's candidates and examples into the network
   result and attaches `LexicalInfo`.

Measured here on `bank` with warm caches:

| Stage | Time |
| --- | --- |
| Apple dictionary partial | 124 ms |
| Google | 322 ms |
| Cambridge | 989 ms |
| final, merged | 990 ms |

With the network unreachable the same query answers in 27 ms from the
dictionary alone.

## Verified facts

Everything below was produced by running it here, on macOS 26.5.2 (arm64,
Command Line Tools only, no Xcode).

- `RegisterEventHotKey` (Carbon) returns `noErr` with no TCC permission.
- `AXIsProcessTrusted()` is false until the user grants Accessibility, so
  selection capture must degrade to a Services item and the hotkey.
- `DCSCopyTextDefinition` works from an unsigned CLI binary, about a
  millisecond warm, and returns the Oxford Russian Dictionary entry with IPA
  and `▸` example pairs.
- `DCSCopyDefinitionMarkup` segfaults with the naive signature — do not use it.
  `DCSCopyRecordsForSearchString` plus `DCSRecordCopyData` is the structured
  path, and its getters return unretained values.
- `TranslationSession(installedSource:target:)` works headless, but only for an
  already-installed pair. `canRequestDownloads` is false outside SwiftUI, both
  for a plain binary and for an ad-hoc-signed bundle, so the download has to be
  triggered once from `.translationTask` plus `prepareTranslation()`.
- en→ru is `supported` but not installed by default; 38 languages are supported.
- SwiftUI Liquid Glass (`glassEffect`, `GlassEffectContainer`) compiles with
  `swiftc -target arm64-apple-macos26.0` under Command Line Tools.
- The bundled CPython keeps FTS5 (SQLite 3.53.1) and `threadsafety == 3`.

## Layout

| Path | Role |
| --- | --- |
| `desktop_app/platform/paths.py` | every macOS directory, with env overrides |
| `desktop_app/platform/macos/` | protocol, socket server, session, daemon, CLI client |
| `translate_logic/infrastructure/providers/apple.py` | sidecar client and merge inputs |
| `macos/AppleLangHelper/` | Swift sidecar (SwiftPM) |
| `macos/Translator/` | SwiftUI shell (SwiftPM) |
| `scripts/build_macos_app.sh` | assembles `dist/Translator.app` |
| `scripts/install_macos.sh` | install, update, rollback, remove, healthcheck, status |
| `scripts/run_backend_macos.sh` | dev launcher for the daemon |
| `.github/workflows/macos.yml` | gate, sidecar, bundle, notarize |

## Release

`scripts/build_macos_app.sh` produces an ad-hoc-signed bundle that runs locally.
Distribution needs a Developer ID certificate: the `notarize` job runs only on
tags and only when `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`,
`APPLE_SIGNING_IDENTITY`, `APPLE_CERT_BASE64` and `APPLE_CERT_PASSWORD` are set.
Without them it skips with a notice rather than failing.

Offline bases stay out of code releases. `scripts/db-bundle.lock.json` pins the
bundle tag and the sha256 of each file, and the installer verifies a download
before promoting it.
