# Installing on macOS with an agent

One command takes a checkout to a working install. It builds the bundle, installs it,
verifies the 1.8 GB of offline databases by checksum (downloading only what is missing),
starts the login agent, waits for it, and translates one word through it:

```bash
scripts/agent_install_macos.sh
```

It ends with a block an agent can parse, so nothing has to be inferred from prose:

```
=== TRANSLATOR_INSTALL_REPORT_BEGIN ===
{
  "state": {
    "installed_app": "/Users/you/Applications/Translator.app",
    "backend_running": true,
    "backend_version": "0.3.0",
    "databases_present": true,
    "database_dir": "/Users/you/Library/Application Support/Translator/db",
    "apple_dictionary": true,
    "dictionaries": ["Oxford Russian Dictionary …", "Apple Dictionary"],
    "apple_translation": true,
    "translation_status": "installed",
    "accessibility_granted": true,
    "accessibility_state": "yes"
  },
  "blocked": [],
  "needs_human_click": [],
  "needs_purchase": ["apple developer id: required only to notarise a build for other machines"]
}
=== TRANSLATOR_INSTALL_REPORT_END ===
```

- `blocked` — something is wrong and the install is not usable; the script exits non-zero.
- `needs_human_click` — a person has to confirm a system dialog. An agent can raise each
  one but must not click a security prompt on the user's behalf.
- `needs_purchase` — money is involved; never automate it.
- `accessibility_state` is `unknown` until the app has run once, which is not the same as
  refused.

`scripts/agent_install_macos.sh --report` re-reads the state without installing anything.

## Prompt for an agent

Paste this as-is. It assumes nothing but a checkout.

> Install this macOS app and get it to a working state.
>
> 1. Run `scripts/agent_install_macos.sh` from the repository root. It is idempotent; run
>    it again rather than repairing by hand.
> 2. Read the `TRANSLATOR_INSTALL_REPORT` block it prints.
> 3. If `blocked` is not empty, fix those first — they are real failures, and the paths to
>    the logs are in the message. Then re-run with `--report`.
> 4. For every entry in `needs_human_click`, open the app's Settings (the Setup section at
>    the top lists the same stages with a button each) and raise the request:
>    `Grant…` for Accessibility, `Download…` for the offline language pair. **Apple's own
>    dialog then asks the user to confirm. Do not click that dialog for them — tell them
>    it is waiting and what it is for.**
> 5. Do not act on `needs_purchase`. Report it and stop there.
> 6. Verify with facts, not assumptions: after each change re-run `--report` and quote the
>    fields that changed. Say plainly which stages are still open.
>
> Open the app when you are done: `open ~/Applications/Translator.app`. It lives in the
> menu bar, and on a launch where a required stage is unfinished it shows Settings itself.

## What the user still has to do, and why

| Step | Why it cannot be automated |
| --- | --- |
| Accessibility grant | A security consent dialog. Automating the click would need the very permission being granted, and it is the user's decision to make. |
| Offline language pair | Apple's download sheet is the sanctioned path; the app can raise it (`translationTask` + `prepareTranslation`), the confirmation is the user's. |
| Apple Developer ID | A paid membership bought with the user's account. Only needed to notarise a build for other machines; the app runs locally on an ad-hoc signature. |

Without the Accessibility grant the shortcut cannot read a selection — neither through the
accessibility API nor through a synthesized copy, since both need the same permission. The
Services menu item on any selected text needs no permission at all and keeps working.

## The notification about an unidentified developer

Installing adds a login item, and macOS announces it. On a locally built app the notice
says the item is from an unidentified developer, because an ad-hoc signature carries no
team identity — only a paid Apple Developer ID does, and buying one is the user's
decision. Nothing is wrong and nothing needs clicking: the item is enabled and allowed.

What the notice names, however, was worth fixing. The login agent used to run a shell
script, and a script cannot carry a signature, so the system could not tie it to the app
and announced a bare `run-backend` — indistinguishable from something the user never
installed. It now runs a signed executable inside the bundle, and the system records it as
the app:

```
Name: Translator
Identifier: 8.com.translator.desktop
Executable Path: …/Translator.app/Contents/MacOS/TranslatorBackend
Disposition: [enabled, allowed]
```

Read that back with `sfltool dumpbtm` (no root needed) and look for the entry named
Translator. The `Developer Name: (null)` line is the part a Developer ID would fill in.

## Uninstalling

```bash
scripts/install_macos.sh remove
```

The offline databases are left in place and the command prints where they are; delete them
separately if you want the disk back.
