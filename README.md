[![Translator — перевод под курсором, из английского в русский](docs/assets/translator-banner.png)](https://github.com/gorodtx/selection_translator_anki/releases/download/v0.3.1-rc.2/Translator-0.3.1-macos-arm64.dmg)

<p align="center">
  <a href="https://github.com/gorodtx/selection_translator_anki/releases/download/v0.3.1-rc.2/Translator-0.3.1-macos-arm64.dmg"><strong>🍎 Скачать для Mac</strong></a> ·
  <a href="https://github.com/gorodtx/selection_translator_anki/tree/gnome#русский"><strong>🐧 GNOME / Arch Linux</strong></a> ·
  <a href="https://github.com/gorodtx/selection_translator_anki/issues">💬 Обратная связь</a>
</p>

<p align="center">Apple Silicon · macOS 26+ · DMG 27,40 МБ</p>

<p align="center">
  <a href="https://developer.apple.com/documentation/swiftui"><img src="site/assets/badges/swiftui.svg" alt="SwiftUI"></a>
  <a href="https://developer.apple.com/documentation/appkit"><img src="site/assets/badges/appkit.svg" alt="AppKit"></a>
  <a href="https://developer.apple.com/documentation/translation"><img src="site/assets/badges/translation.svg" alt="Apple Translation"></a>
  <a href="https://www.gtk.org/"><img src="site/assets/badges/gtk.svg" alt="GTK4"></a>
  <a href="https://www.python.org/"><img src="site/assets/badges/python.svg" alt="Python"></a>
  <a href="https://docs.aiohttp.org/"><img src="site/assets/badges/aiohttp.svg" alt="aiohttp"></a>
  <a href="https://spacy.io/"><img src="site/assets/badges/spacy.svg" alt="spaCy"></a>
  <a href="https://sqlite.org/fts5.html"><img src="site/assets/badges/sqlite.svg" alt="SQLite / FTS5"></a>
  <a href="https://github.com/amikey/anki-connect"><img src="site/assets/badges/anki.svg" alt="AnkiConnect"></a>
</p>

Выделите английский текст и вызовите Translator сочетанием клавиш. Русский перевод появится под курсором; история и добавление в Anki — рядом.

## ▶ Демонстрация

<table align="center"><tr><td width="664">

https://github.com/user-attachments/assets/1d40c4a2-1794-4447-b1a3-518d374e3714

</td></tr></table>

macOS и Linux · Python backend · SQLite · Anki. [Код и разработка](docs/development.md).

## 📚 Офлайн-базы

| База | Содержимое |
| --- | --- |
| [`primary.sqlite3`](https://github.com/gorodtx/selection_translator_anki/releases/download/db-a6f07d1e1c28/primary.sqlite3) | Основные англо-русские примеры и лексикон |
| [`fallback.sqlite3`](https://github.com/gorodtx/selection_translator_anki/releases/download/db-a6f07d1e1c28/fallback.sqlite3) | Дополнительные англо-русские примеры |
| [`definitions_pack.sqlite3`](https://github.com/gorodtx/selection_translator_anki/releases/download/db-a6f07d1e1c28/definitions_pack.sqlite3) | Английские определения |

Базы скачиваются из настроек приложения и хранятся локально; с каждым обновлением приложения повторная загрузка не нужна. [Готовый комплект и SHA256](https://github.com/gorodtx/selection_translator_anki/releases/tag/db-a6f07d1e1c28).

---

© 2026 Translator contributors · [Лицензия MIT](LICENSE)
