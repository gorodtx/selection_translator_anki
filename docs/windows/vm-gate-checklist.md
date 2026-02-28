# VM Gate Checklist (Windows 11 23H2+)

Gate run id: `TBD`  
Operator: `TBD`  
Commit: `TBD`  
Artifact: `TBD`

## A. Runtime and Startup

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| App starts from portable zip |  |  |
| Second start does not create second instance |  |  |
| Helper/backend IPC connection established |  |  |

## B. Hotkey and Selection

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| Global hotkey opens translation window |  |  |
| Global hotkey closes or toggles as expected |  |  |
| UIA selection works in Notepad |  |  |
| UIA selection works in browser |  |  |
| Clipboard fallback works when UIA unavailable |  |  |
| Hotkey spam (10-20 presses) has no freeze |  |  |

## C. Tray and Entrypoints

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| Tray icon visible after startup |  |  |
| Tray opens Settings |  |  |
| Tray opens History |  |  |
| Repeated open/close keeps stable state |  |  |

## D. Translation UX

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| Translation success path renders result |  |  |
| Network error path handled without crash |  |  |
| Notifications auto-hide as expected |  |  |

## E. Anki Required Flow

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| GetAnkiStatus works when AnkiConnect is available |  |  |
| Create model works |  |  |
| Deck list/select works |  |  |
| Add card works |  |  |
| Update card works |  |  |
| Disabled Anki path reports graceful error |  |  |

## F. Stability and Exit

| Step | Result (PASS/FAIL) | Notes |
|---|---|---|
| Repeated translate does not freeze UI |  |  |
| Settings/History stress loop does not freeze |  |  |
| App exits cleanly |  |  |
| Relaunch after exit has clean state |  |  |

## Evidence Inventory

| Evidence | Path | Present |
|---|---|---|
| Checklist | `vm-gate-checklist.md` |  |
| Manifest | `env-manifest.json` |  |
| App log | `logs/app.log` |  |
| Helper log | `logs/helper.log` |  |
| IPC log | `logs/ipc.log` |  |
| Video | `video/gate-run.mp4` |  |

## Final Gate Decision

- Decision: `PASS` / `FAIL`
- Blocking issues:
- Waivers (if any):

