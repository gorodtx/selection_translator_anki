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

Measured here over ten single words (`bank`, `time`, `run`, `light`, `book`,
`point`, `well`, `child`, `spring`, `match`), cold HTTP cache for the first row:

| Configuration | first partial p50 | first partial p95 |
| --- | --- | --- |
| network only | 307 ms | 734 ms |
| network + Apple | 16 ms | 22 ms |

The dictionary answers roughly twenty times faster than the fastest network
provider, so on macOS the popup is filled before Google has replied. The final
merged result still waits for the network, which on a cold cache lands between
300 ms and 1 s.

Per-provider timings for a single `bank` lookup:

| Stage | Time |
| --- | --- |
| Apple dictionary partial | 124 ms (cold sidecar spawn) |
| Google | 322 ms |
| Cambridge | 989 ms |
| final, merged | 990 ms |

### Dictionary coverage

Two paths exist. The structured one parses the entry markup returned by
`DCSCopyRecordsForSearchString`; the flat one parses the plain text of
`DCSCopyTextDefinition` and is only a fallback. Measured over the same 22 probe
words:

| Path | words with candidates | with IPA | with examples | p50 | p95 |
| --- | --- | --- | --- | --- | --- |
| structured markup | 21 / 22 | 21 | 20 | 17 ms | 21 ms |
| flat text | 18 / 22 | 18 | 16 | 13 ms | 26 ms |

The flat path has two gaps the structured one closes:

- **Phrasal verbs are invisible to it.** `make up`, `take off` and `break down`
  return nothing; `look up` and `get over` return the whole `look` / `get`
  article instead of the phrasal sub-entry. Through the structured path they
  resolve correctly: `look up` to навещать / отыскивать, `make up` to
  доплачивать / возмещать, `take off` to снимать / уводить.
- **Only the first homograph reaches it.** `bank` yields the river-bank article
  and never the financial one, even though the dictionary holds three records.
  The structured path merges all of them into one card.

Whichever path answers, the pipeline still guards against a mismatched entry:
a definition whose headword does not match is only applied to single-word
queries, and phrasal blocks belonging to another phrase are dropped. An
inflected form resolves to the base article, so `went` arrives as the whole of
`go`: 26 blocks, 22 of them phrasal verbs like `go about` and `go back` that
translate nothing the reader asked for. Filtering them leaves 5 blocks and 17
candidates instead of 26 and 33. A record that is itself phrasal, such as
`look up`, is left untouched.

Over a wider 38-word probe the structured path answered 35. The three that did
not are dictionary gaps rather than parser defects, and the network providers
cover all of them:

| Word | What the dictionary holds | Result |
| --- | --- | --- |
| `get over` | a phrasal section with two example sentences and no sense-level translation | card with examples, no candidates |
| `run into`, `figure out`, `deal with`, `rely on`, `put up with`, `in spite of` | no entry under any search method (exact, prefix, wildcard) | no card |

Inventing a gloss out of `get over`'s example sentences was tried and rejected
on the numbers: across 30 words it recovered two correct translations and
introduced six wrong ones, because those sentences translate idioms rather than
the headword.

One trap worth naming. Oxford marks case government with a Latin letter after a
plus: `наталкиваться на + a`, `следить за + i`, `отчитываться в + p`. The
candidate cleaner drops anything carrying Latin letters, so it used to throw
those translations away whole, and an article whose senses all govern a case
produced nothing at all. Stripping the marker before the Latin check recovered
38 candidates over 30 words and lost none: `come across` went from 0 to 7,
`look after` from 1 to 6, `account for` from 4 to 11.

**Entries are big.** The Oxford article for `set` is about 106 KB of markup and
arrives as a single NDJSON line, and `run` is 87 KB. asyncio's default stream
limit is 64 KB, so the client raises its subprocess limit to 8 MB and drops an
oversized line rather than letting the reader task die with it.

Both gaps close once `markup` is present, measured on the same words through
`apple_dcs`:

| Query | Flat text | Structured records |
| --- | --- | --- |
| `bank` | 1 article, 11 candidates | 3 homographs, 7 blocks, 19 candidates |
| `look up` | whole `look` article, 36 senses | the `look up` section, 10 candidates |
| `take off` | nothing | 3 blocks, 11 candidates |
| `went` | entry found, 0 candidates | senses of `go`, 33 candidates |

Records carry the disambiguation the flat string drops: a homograph number, a
`title` naming the lemma an inflected form belongs to, and an `anchor` of the
form `xpointer(//*[@id='…'])` pointing at the phrasal-verb section inside the
parent entry. `apple_dcs.lexical_from_records` follows the anchor when it is
present, keeps the headword the dictionary matched (`look up` stays `look up`,
`went` stays `went`), and merges homographs into consecutive part-of-speech
blocks marked with the dictionary's own superscript (`noun¹`, `noun²`).

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
  path, and its getters return unretained values. Declare every `DCSGet…`
  function as returning `Unmanaged<…>`; taking the value directly traps when
  Swift releases a +0 reference. Search methods observed: 0 exact, 1 prefix,
  3 wildcard. A multi-word idiom with no headword of its own (`in spite of`)
  returns nothing at all.
- The sidecar must not block its main thread. Dictionary Services and
  Translation deliver replies through the main queue, so a `readLine` loop or a
  semaphore on the main thread hangs the first request forever; the sidecar
  reads stdin on its own thread and leaves the main thread in `dispatchMain()`.
- Command Line Tools ship Swift Testing in
  `Library/Developer/Frameworks` without telling SwiftPM, and no XCTest at all.
  `scripts/swift-test.sh` adds the framework and `lib_TestingInterop.dylib`
  search paths; a package also needs `platforms: [.macOS(.v14)]` or the test
  macros fail to expand.
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
| `translate_logic/infrastructure/providers/apple_dcs.py` | entry markup to `LexicalInfo` |
| `macos/AppleLangHelper/` | Swift sidecar (SwiftPM) |
| `macos/Translator/` | SwiftUI shell (SwiftPM); `TranslatorCore` holds the pure, testable layer |
| `scripts/build_macos_app.sh` | assembles `dist/Translator.app` |
| `scripts/install_macos.sh` | install, update, rollback, remove, healthcheck, status |
| `scripts/run_backend_macos.sh` | dev launcher for the daemon |
| `.github/workflows/macos.yml` | gate, linux-parity, sidecar, shell, bundle, notarize |

## Running the whole stack

```bash
scripts/run_backend_macos.sh &                       # Python daemon on the socket
scripts/build_macos_app.sh --out dist                # -> dist/Translator.app (57 MB)
open dist/Translator.app                             # menu-bar item, no dock icon
```

The shell has debug entry points so the UI can be driven without a selection or a
shortcut: `TRANSLATOR_DEBUG_TEXT="bank"` opens the popup on that text at launch,
and `TRANSLATOR_DEBUG_WINDOW=settings|history|anki` opens one window.
`macos/Translator/scripts/mock_backend.py` answers the real protocol with canned
data, including the two-phase timing, for working without Python running.

Verified end to end here: the bundled shell connected to the live daemon
(`ipc client connected`) and drove two real translations through the pipeline
with per-provider timings in the log.

Protocol drift is caught by CI: the `shell` job extracts every `Method` and
`Event` literal from `protocol.py` and fails if any is missing from
`TranslatorCore/Protocol.swift`.

## Popup geometry

The popup sizes itself to its content and caps the scrollable body at half the
screen's visible height, clamped to 360–640pt. Measured against the live
backend on a display whose visible height is 1073pt, so the cap is 536pt and
the chrome around it 134pt:

| Query | Width | Height | Why |
| --- | --- | --- | --- |
| `in spite of everything he said` | 380 | 174 | a sentence: translation only, no dictionary card |
| `serendipity` | 480 | 600 | one sense, still under the cap |
| `bank`, `set` | 480 | 670 | at the cap, body scrolls |

Every real word lookup reaches the cap, because a card carries IPA, sense
blocks, five definitions and three examples. That makes the cap, not the
content, decide how much is readable without scrolling, which is why it follows
the screen rather than a fixed number. The body carries a soft scroll edge
effect so content passing under the action bar reads as continuing rather than
clipped.

Window geometry is measurable without Screen Recording, through
`CGWindowListCopyWindowInfo`, and it is the only automated acceptance available
for the interface here. It proves layer, size and that a window exists at all.
It says nothing about colour, typography, legibility on glass, or the Reduce
Transparency path — those need a person.

## Anki

Anki cannot be installed on a build machine, so the add / update / merge / image
path is covered by an in-process AnkiConnect stand-in that serves the real wire
protocol over a local socket (`tests/fakes/anki_connect.py`). It implements only
the actions the client calls; anything else answers with an error, the way a
version mismatch would.

Driven through the daemon over its own socket, with `ANKI_CONNECT_URL` pointed
at the stand-in, the observed action sequence is:

```
modelNames  deckNames  findNotes  addNote  findNotes  notesInfo
```

and the note that lands carries the mapped fields, the query term highlighted
and definitions in italics:

```
word: bank
translation: банк; берег
definitions_en: <i>a financial institution</i>
example_en: Most <mark class="hl">banks</mark> are reluctant.
```

### What it does not do

Matching keys on the configured field name, so only notes already in the app's
own shape are found. A note whose fields are called `Word` and `Translation`
is fetched but never matched — the app cannot know that `Word` holds the
headword. The consequence is worth stating plainly: **pointed at an existing
hand-made deck, the app adds new notes rather than updating the ones already
there.** Upsert works on decks the app itself has filled.

Two related behaviours, both deliberate: `create_model` owns the field mapping
and overwrites whatever `settings.save` stored, because its own model has its
own field names; and the field list offered in the sheet dedupes
case-insensitively, so `word` and `Word` never appear as two separate fields.

Writing that harness found a real defect. `findNotes` returning `[]` — the
normal answer for a word being added for the first time — was reported as
"Invalid AnkiConnect response", because the guard meant to catch a malformed
payload also fired on a legitimate empty list. The same held for a profile with
no models, which is exactly the state `createModel` exists to fix.

## Permissions

| Path | Permission | If denied |
| --- | --- | --- |
| Services menu item | none | always available |
| Global shortcut (`RegisterEventHotKey`) | none | always available |
| Reading the selection via Accessibility | Accessibility | falls back to a synthesized ⌘C |
| Downloading the en→ru pair | none, but needs SwiftUI | machine translation stays off |

Screenshots and window inspection from a terminal additionally need Screen
Recording and Accessibility for that terminal; without them `screencapture`
fails with "could not create image from display" and System Events returns
-1728.

## Release

`scripts/build_macos_app.sh` produces an ad-hoc-signed bundle that runs locally.
Distribution needs a Developer ID certificate: the `notarize` job runs only on
tags and only when `APPLE_ID`, `APPLE_TEAM_ID`, `APPLE_APP_PASSWORD`,
`APPLE_SIGNING_IDENTITY`, `APPLE_CERT_BASE64` and `APPLE_CERT_PASSWORD` are set.
Without them it skips with a notice rather than failing.

Offline bases stay out of code releases. `scripts/db-bundle.lock.json` pins the
bundle tag and the sha256 of each file, and the installer verifies a download
before promoting it.
