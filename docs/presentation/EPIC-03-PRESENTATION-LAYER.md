# Эпик 3 — Presentation Layer

Создан: 04.10.2026. Статус: **MINIMAL_LAYOUT_LOCAL_ACCEPTED; WAITING_USER_VIDEO_LOGO; ROOT_DELIVERY_PENDING**. Владелец после передачи: существующая полная сессия Translator1-Distribution, GPT-6.1-Sol xhigh. Main параллельно ведёт ручную приёмку native-приложения с пользователем. Новых агентов создавать не нужно.

## Действующий steering — 04.10.2026 19:38UTC

User instruction через Root `msg_4eb531224ca9` заменяет generated/demo часть прежнего scope: **пользователь сам записывает настоящее видео и создаёт новый логотип**. Задача peer — очень минимальные русский landing/README, практически без текста, с real-video integration slot, текущей иконкой только как provisional, system/native typography/material/spacing/motion. Не генерировать видео/лого, не рисовать app demo/mockup/переводы и не имитировать capture. Native app неизменен. DB checkpoint сохранён как исследование и **PAUSED**, дальнейшие DB implementation/checks прекращены. Первоначальные критерии ниже остаются историей; status table отражает новое решение. ACK `msg_84c04c61fd1a`.

Дополнение Root `msg_3759f3009620` (19:43UTC): одна колонка/короткий meaning line/central real-video/один CTA,30–50words без необходимых release details; SF/system/native palette, light/dark, thin purposeful material. Никаких features grids/how steps/faux OS/dup CTA/technical status/source digest paragraphs в public UI. Provisional icon помечается только metadata/docs. Native video controls/playsinline/preload metadata/noautoplay; CSS transform/opacity ≤150ms, reduced motion/keyboard immediate. Генерируемые assets удалены из active source, DB work paused, история внешне сохранена. **Delivery blocker:** Root нашёл `.gitignore:314 /site`; peer не меняет ignore/index, exact named site paths передаются Root для узкой delivery adjustment. Public URL/deploy/native runtime не заявляются.

Root read-only review `msg_e128f3ec607a` (19:52UTC) принял минимальный layout локально: лично просмотрел четыре PNG, подтвердил HTTP200/byte-match entry, Node syntax и diff whitespace. Peer отдельно проверил Chromium desktop/mobile/light/dark, keyboard skip/focus, reduced motion, empty и missing-video fallback. Это локальная приёмка presentation; настоящий footage, Safari playback, новый logo, Git/CI и public deploy остаются отдельными gates. Точный комплект и commit plan — [HANDOFF.md](HANDOFF.md), команды и границы — [журнал](PROGRESS-DELIVERY.md).

## Результат для пользователя

Два согласованных представления Translator: короткий русский GitHub README и русскоязычный лендинг. Посетитель сразу понимает сценарий «выделить английский текст → получить русский перевод», видит один убедительный пример и находит актуальное скачивание. Техническая документация доступна по ссылкам, не занимает первый экран.

В состав входит исследование и подготовка демонстрационного ролика; отдельным checkpoint — исследование интерактивного переводчика и поиска примеров в тех SQLite-базах, которые приложение скачивает. Это будущая возможность, а не обещание уже реализованной web-версии.

**Дизайн и код native-приложения не входят в этот эпик.** Не изменять SwiftUI/AppKit, системную типографику, Liquid Glass, layout, assets, анимации, перевод, историю, backend/helper и существующие настройки. Лендинг представляет текущий продукт, используя его настоящую идентичность и подтверждённые возможности.

## Актуальная база и факты

- Repository: `/Users/den/Documents/dev/selection_translator_anki`, branch `mac`, base initial brief `ea5dd631de468bb27d28af16e2b0725bcf7db28a`; implementation base `ab838767b29744f13463749c86e2443bf306e293`.
- [Prerelease v0.3.0](https://github.com/gorodtx/selection_translator_anki/releases/tag/v0.3.0): 0.3.0 (295), release tag `84b185256ccdcc7eae5a8a0114f6cec6f09c3004`, Apple Silicon, macOS 26+; DMG 25 229 806 bytes.
- Production source digest `c248d674a64b71546d3766d508431ac9dcde995af75e9f294f5064e4020b73fd`. Сохранены настоящие guest screenshots и измеренная функциональная приёмка в [эпике приложения](../release/EPIC-02-APPLICATION.md) и [progress](../release/PROGRESS-DELIVERY.md).
- Apple Developer Program отсутствует. D05 Developer ID/notarization/Gatekeeper BLOCKED. В публичном тексте рядом со скачиванием ясно обозначить предварительный выпуск и текущую границу установки; не обещать беспроблемный публичный первый запуск.
- Три SQLite-базы, 1 896 546 304 bytes, опубликованы отдельно в [db-a6f07d1e1c28](https://github.com/gorodtx/selection_translator_anki/releases/tag/db-a6f07d1e1c28). Кодовые релизы повторно их не публикуют. Не добавлять SQLite в Git, сайт или video assets.
- Primary language README/лендинга — русский. Английская версия сейчас не нужна. Поддержку Linux не стирать из документации, но главный пользовательский сценарий текущего захода — macOS EN→RU.
- Shared daily budget обеих существующих сессий: максимум 40% daily usage. Точный счётчик в доступных инструментах UNKNOWN. Не раздувать число сессий, не повторять VM/скачивание баз/полные native suites ради текста или сайта.

## Владение файлами и доставка

Presentation owner получает `README.md`, `docs/presentation/**`, новую директорию `site/**`, при необходимости отдельную `video/**` и технический migration document `docs/development.md`. Стек выбрать после исследования; не устанавливать React/shadcn/GSAP/Remotion только из-за наличия skill или компонента.

Main сохраняет владение native/backend/tests/release scripts, существующим `docs/release/**`, установленным приложением, пользовательскими профилями и shared Git index. После передачи Main не редактирует presentation-owned файлы поверх peer. Peer не меняет Git index/HEAD, gates, signing, tags, release assets, deployment/DNS или App Store без отдельной передачи этого владения. Подготовить логичный план named commits; send Main точные owned paths, diff и результаты проверок. Предыдущий frozen handoff P029 заменён новым ownership только в перечисленных presentation paths.

Работать до завершения доступного исследования и реализации, не останавливаться после плана. Не ждать пользователя для обратимых решений. Зависимость от новой записи Screen Studio, домена, лицензии или доступа фиксировать отдельно и продолжать остальные задачи. Публичный deploy — отдельный проверяемый этап; локальный preview не называть опубликованным сайтом.

## Подзадачи и проверяемая приёмка

| ID | Подзадача | Приёмка | Статус |
| --- | --- | --- | --- |
| P01 | Аудит README, product facts, assets, существующих design/motion правил и условий выпуска | Конкретные проблемы и подтверждённые продуктовые формулировки, пути/источники; никаких изменений app | PASS_SOURCE |
| P02 | Полное исследование хороших README и лендингов | Отдельный [RESEARCH.md](RESEARCH.md): минимум 5 релевантных README и 5 лендингов, прямые первичные ссылки/даты, сравнение, полезные приёмы, отклонённые варианты и причины | PASS_RESEARCH |
| P03 | 21st.dev MCP refs | Рассмотреть mechanics selection, contextual popup, product demo и камерные переходы. IDs/author/URL/лицензия и реальные preview observations; metadata не считать просмотром. Не копировать чужой брендинг и source без проверки лицензии | PASS_PREVIEW_SCOPE |
| P04 | Выбор production-пути для ролика | Сравнение Screen Studio, Remotion и хотя бы одного адекватного альтернативного подхода: достоверность, контроль анимаций, время, лицензия, exports, доступные инструменты, воспроизводимость. Рекомендация и fallback | SUPERSEDED_USER_CAPTURE |
| P05 | Сценарий одного убедительного демо | Уточнить [VIDEO-BRIEF.md](VIDEO-BRIEF.md): 20–35 секунд, выделение → Services → перевод; один главный пример, русский текст, понятные планы/тайминг, минимум вторичных действий | READY_FOR_USER_CAPTURE |
| P06 | Русский README | Короткий продуктовый README: иконка/название/суть → один demo → скачать macOS с актуальным prerelease → короткая настройка и нужные ссылки. Без стены technology badges/CLI/архитектуры. README-полотно переносится в docs с сохранением полезной информации | IMPLEMENTED_MINIMAL |
| P07 | Лендинг | Реально запускаемый responsive preview, README и сайт говорят об одном продукте. Один центральный demo, ясный CTA, существующая визуальная идентичность, точные platform/release условия. Нет фальшивой статистики, testimonials, работающих функций или несуществующего URL | PASS_MINIMAL_LOCAL; WAITING_REAL_ASSETS |
| P08 | Демонстрация без участия пользователя | Подготовить анимированный сценарий/композицию из доступных настоящих assets и собственных примеров. Code-based illustration маркировать как illustration; не выдавать её за screencast/runtime proof. Если выбран Remotion — исходники, preview, render command и проверенный короткий render; если не выбран — аргументированный простой вариант | SUPERSEDED_NO_GENERATION |
| P09 | Настоящий screencast и финальный монтаж | При наличии разрешённого footage — интеграция/титры/zoom/transitions/export. До новой записи пользователя сохранять готовый capture brief и composition без фальшивого DONE | WAITING_USER_VIDEO_LOGO |
| P10 | Отдельный checkpoint интерактивного переводчика/DB | Исследовать реальные SQLite schema/providers, browser WASM/File API/worker versus локальный read-only endpoint. Описать память/1.9GB/индексы/FTS/limits/лицензии/приватность/ошибки/совместимость; рекомендовать архитектуру и этапы | PASS_READ_ONLY_RESEARCH; PAUSED |
| P11 | Ограниченный interactive prototype | Реализовать без изменения native app, если это можно сделать изолированно и без пользователя. Selection → contextual translation UI с визуально согласованной motion; fixture versus real DB явно отличать. Никакой скрытой загрузки 1.9GB. При настоящей DB — read-only, ограниченные запросы, настоящие ответы, release/source identity и обработка ошибок | PAUSED_USER_STEERING |
| P12 | Проверки и evidence | Реальные desktop/mobile screenshots, keyboard/focus/reduced-motion, понятный loading/error/empty, ссылки/assets/build, playback и консоль. Запуски/версии/viewport/ошибки/ограничения и originals в [PROGRESS-DELIVERY.md](PROGRESS-DELIVERY.md) | PASS_SCOPED_BROWSER; REAL_PLAYBACK_UNVERIFIED |
| P13 | Логичная Git/hosting доставка | Точный named path plan, только собственные изменения, нормальные gates. Current local, commit, push, CI, preview и public deployment считаются отдельно. Hosting план/готовая конфигурация допустимы; DNS и новый внешний deploy не объявляются сделанными заранее | HANDOFF_PREPARED; ROOT_GIT_DEPLOY_PENDING |

## Обязательное содержание исследования

Исследование не сводить к галерее ссылок. Для каждого референса фиксировать автор/проект/прямой URL, дату обращения, проверенную популярность при её упоминании, первый экран, порядок информации, место демо/скачивания, что подходит Translator и что противоречит заданным рамкам. Репозитории Rectangle, Maccy, IINA, Kap и Keka можно рассмотреть как кандидатов; актуальность и пригодность проверить, а не предполагать.

Screen Studio — референс подачи и tool для настоящего capture, а не разрешение копировать сайт/бренд. Remotion — кандидат video-as-code; проверить текущие API, лицензию и локальный render. Не покупать платные templates или подписки и не включать cloud rendering ради первого прототипа. 21st.dev использовать по пользовательскому запросу; [первичная metadata подборка](21ST-REFERENCES-2026-10-04.json) уже получена, code не извлекался и визуальные previews ещё не просмотрены.

Интерактивный переводчик — отдельный checkpoint. Сначала закончить README/лендинг и выбрать video flow, затем изолированный proof-of-concept. Не переносить native business logic на новый стек и не публиковать огромную DB через сайт. Локальные пользовательские БД и Anki-данные не изменять. Публичная выдача dictionary examples требует проверки прав на контент; MIT license кода не означает автоматически ту же лицензию всех источников данных.

## Progress и критерий завершения

После исследования, выбора, реализации, ревью, запуска, просмотра screenshots и запроса добавлять датированную запись в [PROGRESS-DELIVERY.md](PROGRESS-DELIVERY.md): ID, действие, источник/base, конкретный результат, команда/выход или visual evidence, найденный дефект, следующий шаг и scope. Не стирать старые FAIL/PASS и требования. Эпик постоянно дополнять новыми знаниями/критериями; актуальные статусы менять с сохранением датированной истории.

Эпик завершён, когда короткий русский README и запускаемый лендинг представлены и проверены, исследование и video decision/capture brief полны, доступное demo реализовано, условные зависимости названы точно, DB checkpoint имеет проверенную архитектуру/PoC либо конкретное обоснование границы, а Git/hosting результат отделён от локальных проверок. Недоступный footage/hosting/лицензия не превращаются в выдуманный PASS.

## 05.10.2026 — Translator Mono, локальная web-приёмка

Обновление 2026-10-05T13:32:05.166328+00:00, Task task_431645af094f / Dispatch ctx_3f3fce8391c7 / Run run_9d43c4e32803. Новая база6931540ad76a6ab7a5abe70d49c513e93e881d36, роль Translator-Brand-Web; прежние даты/статусы выше сохранены. Пользователь принял artwork, пять production assets совпали с утверждёнными exports и manifest по bytes/SHA256; logoProvisional=false. Small32px navbar и Dark Small через picture/prefers-color-scheme, Tiny SVG/ICO16+32 и apple-touch180 интегрированы; существующие системные fonts/blue-neutral palette/one-column/CTA сохранены.

Текущий статус логотипа: APPROVED_INTEGRATED; local source/HTTP/Chromium PASS. Настоящее video/poster/captions остаются null и WAITING_USER_VIDEO: прежнее WAITING_USER_VIDEO_LOGO теперь применимо только к видео. Desktop1440/mobile390 light/dark/reduced/keyboard/favicons/root/subpath проверены,6actualPNG лично просмотрены; report [design/integration/web.md](../../design/integration/web.md). Browser initial theme mismatch RED сохранён: измеренное picture currentSrc обновлялось после media смены, harness исправлен ожиданием actualdecodedvariant; production не менялся для обхода проверки.

Safari/WebKit/physical devices и настоящая запись UNVERIFIED; livePenpot doctor/overview fetch failed и UNKNOWN, сервис не перезапускался. Own preview после actualchecks остановлен exactPID29720, listener8873 исчез; фоновый preview не оставлен. D05 ad-hoc prerelease/publicGatekeeper граница у CTA сохраняется; publichosting/deploy не выполнялись, Gitindex/commit/push/CI только Coordinator. Полный эпик не объявляется завершённым по приёмке логотипа.


## Дополнение 08.10.2026 — README, скачивание и установка

Новое поручение пользователя дополняет историю и заменяет публичный слоган: удалить «Перевод рядом. Из хаоса — в ясность.». Верх README — переданный пользователем `norm.png`, без перерисовки; широкая кликабельная панель по образцу Prettier. Референс структуры: https://github.com/toeverything/affine. Social preview и изображение внутри README проверяются отдельно.

- [ ] P08.1: сохранить точные bytes баннера, показать его первым в README, клик ведёт на Mac DMG.
- [ ] P08.2: короткие ссылки «Скачать для Mac», «GNOME / Arch Linux», «Обратная связь» с минимальными ассоциативными знаками; прежний слоган и prominent prerelease label убрать. Реальные ограничения подписи сохранить в условиях установки.
- [ ] P08.3: добавить компактные ссылки на фактически используемые технологии и три SQLite-базы; не выдавать общий AGENTS stack за стек проекта. Корпус переиспользуется, не загружается заново.
- [ ] P08.4: demo preview ведёт к скачиванию; настоящее видео остаётся отсутствующим, пока его не передаст пользователь. Native video controls не ломать ссылкой поверх плеера. Сайт сохраняет SF/system, палитру и одну колонку.
- [ ] P08.5: проверить source/HTML/JS/asset/link delivery отдельно. Computer-use и новая browser acceptance остановлены пользователем; не объявлять их пройденными.
- [ ] P08.6: отдельная полная macOS-сессия исследует Google Drive-подобную установку без drag, checkbox «Удалить установщик» по умолчанию включён; после исследования обсуждение с пользователем, реализация только после выбора. Владеет `docs/installer/`; общий Root журнал не правит.

Root: native01a1030e-0fcc-7430-8c9d-070c3f569b23, cwd `/Users/den/Documents/dev/selection_translator_anki`, branch mac, base f7db5653ed7c503f554d4fadfc9e531bcda068b1. Новый scope README/site/docs; production app и опубликованные release artifacts не меняются. Установщик — отдельный исследовательский этап, его код ещё не готов.


### P08 checkpoint — 08.10.2026

P08.1–P08.4 source PASS, P08.5 static/HTTP/GFM PASS; source commit1310b5f. Delivery ещё pending. New browser/CUA явно NOT_DONE_USER_STOPPED. P08.6 handoff PASS + receiving ACCEPTED; research ещё выполняется, implementation ожидает будущего пользовательского выбора. Требования и результаты выше сохранены, не вычеркнуты.


### P08 delivery checkpoint — 08.10.2026

P08.1–P08.5 source/static/public README delivery **PASS**: remoteffbd50b, firstbanner/public exact bytes, root/subpath HTTP, all download/data/technology links. Browser/CUA acceptance исключена текущим steering и не объявлена PASS. P08.6 standalone assignment и полный research **PASS**; обсуждение **PENDING USER**. Установщик не реализован по прямому условию пользователя «сначала research, потом обсуждение»; новый EPIC-04 сохраняет будущие14criteria. Новые CI/public site/video/Gatekeeper acceptance остаются отдельными уровнями.

## Дополнение 10.10.2026 — настоящее демо и компактный публичный текст

Новое прямое поручение: удалить публичные длинные блоки «Службы», ad-hoc/первое открытие, источники данных и дополнительную строку установки/версии; технологии оформить логотипами как на пользовательском референсе; добавить MIT footer и переданный `translator_demo.mp4` в README/site; строку архитектуры ужать и обозначить платформы. Прежние требования и RED остаются историей. Native/runtime/release/DB не меняются.

- P10.1 source **PASS**: перечисленные строки удалены, полезные инструкции сохранены в linked docs.
- P10.2 source **PASS**: 9локальных SVG technology badges с реальными встроенными paths, provenance/SHA/licenses и ссылками; внешний runtime fetch отсутствует.
- P10.3 source **PASS**: MIT footer в README/site; строка «macOS и Linux · Python backend · SQLite · Anki». Windows не заявлен при отсутствии реализации.
- P10.4 source/AVFoundation **PASS**: реальный пользовательский MP4 byte-match,43,535с/H.264/1120×1080; poster реальный лично просмотренный кадр, плеер сайта с native controls; README poster→MP4. GitHub inline-player **NOT_DONE_NO_ATTACHMENT_URL**, никакая issue/comment публикация не выполнена.
- P10.5 local **PASS**:2node syntax, named whitespace/base checks,40HTTP root/subpath resources exact bytes; own кратковременный server/fixture остановлены. Browser/CUA/Safari playback/новые responsive screenshots **NOT_DONE_USER_STOPPED**. Public deploy/Git/CI pending Root.

Root подтвердил ownership без пересечения, `msg_15658b87bf64`; attachment boundary, `msg_c92b5aa071ae`. Отчёт/сохранённая сессия/точные evidence: [DELIVERY-2026-10-10.md](DELIVERY-2026-10-10.md). Полный EPIC не объявлен завершённым из-за отдельной редакции README/site.


### 10.10.2026 — уточнение приёмки P10 после независимого review

Источник и локальная HTTP-раздача реального MP4/poster/9logos приняты Root по named23paths. Приёмка доставки требует отдельно commit/remoteSHA/CI; localhost и AVFoundation decode не являются публичным hosting или browser playback. Текущий target mac; вопрос о master не разрешает отдельный merge. Архив и прежние NOT_DONE сохраняются. Запись первой диагностической ошибки и исправленной проверки находится в Progress и root-review.json.


### 2026-10-10T18:07:36.847429+00:00 — P10.6 — компактный inline-плеер в README

Новый пользовательский screenshot выявил недостаток прежней реализации: огромный poster являлся ссылкой на MP4, поэтому видео не воспроизводилось внутри README. Прежний P10.4 сохраняется как история; новое требование заменяет poster→link на встроенный плеер. Заголовок «Технологии» убрать, девять действующих badges перенести непосредственно под строку Apple Silicon / macOS / DMG.

- P10.6.1 **PASS_SOURCE**: девять badges перенесены с сохранением логотипов, alt и ссылок; заголовок удалён.
- P10.6.2 **PASS_SOURCE_RENDER_HTTP**: анонимный GitHub renderer создаёт одно настоящее `<video controls>` из attachment, без ссылки вокруг плеера, autoplay и loop. Компактная версия пользовательской записи — 448×432, H.264, 60fps, 43,535с; звук и длительность сохранены, исходник не изменён. Media из анонимного renderer отдаёт точные bytes, HTTP200 и Range206.
- P10.6.3 **PENDING_DELIVERY**: поимённый commit/push в default `mac`, remote SHA и CI проверяются отдельно. Окончательные receipts сохраняются в журнале исполнения ниже.
- P10.6.4 **NOT_DONE_USER_STOPPED**: новые browser/CUA, физический размер плеера в браузере и ручной Play не объявляются проверенными. Native render/HTTP/decode не подменяют их.

Root выполняет коррекцию самостоятельно. Ownership/Git lease подтверждены Web-сессией, `msg_bf2c156a7a2c`; site и приложение не меняются. [Отчёт](DELIVERY-2026-10-10.md), [журнал исполнения](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-inline/ROOT-PROGRESS.md).


### 2026-10-10T18:34:27.782788+00:00 — P10.7 — служебная панель GitHub и центровка демо

Пользователь прислал screenshot опубликованного2d71bff: нативный GitHub плеер воспроизводится внутри README, но его служебная строка `translator-demo-compact.mp4` нежелательна; полноширинная рамка оставляет пустое место справа. Новый критерий — центрированный компактный блок без этой строки и лишней внутренней ширины. Уменьшение intrinsic видео в P10.6 не ограничило родительский GitHub wrapper, поэтому визуальная приёмка P10.6 **FAIL_USER_SCREENSHOT**; прежние source/HTTP/CI PASS сохраняются отдельно. CI38075173886 completed success:5jobs success, notarize skipped.

![Пользовательский screenshot: служебная строка и пустое место справа](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-centered/user-feedback-wide-wrapper.png)

Screenshot предоставлен пользователем, не получен нашим browser/CUA. Запись `feedback.json` содержит точные origin/SHA. GitHub renderer проверен в11вариантах: обычный внешний `<video>` и `<source>` удаляются; все работоспособные attachment варианты превращаются в `details/summary` с filename. [Официальный pipeline](https://github.com/github/markup#github-markup) подтверждает удаление custom styles/classes. Нативная служебная строка не имеет разрешённого README CSS переключателя.

Центровка **PASS_SOURCE_RENDER_HTTP, NOT_PUBLISHED**: подготовлен ограниченный448px контейнер `table align=center`, реальный video/controls сохранён внутри, media200/Range206 exact bytes, badges9/порядок сохранены. Заголовок **NOT_DONE_GITHUB_COMPONENT**: у native MP4 служебная панель остаётся. Пользователю задан выбор настоящего центрированного видео с native controls или GIF из той же записи без панели/звука/перемотки; ответ ещё не получен, формат не подменён молча. До выбора второй push не выполнен.

Root сохраняет ownership README и трёх presentation журналов, sourcebase2d71bffb4c2a14f6e102fe24c166d96f6356e977; Web frozen, пересечения нет, site/app/release/DB не меняются. [Source receipt](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-centered/source-checks.json); [журнал и resume](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-centered/ROOT-PROGRESS.md). Новый критерий не объявляется PASS по старому CI.


### 2026-10-10T18:41:34.211344+00:00 — P10.8 — пользователь выбрал настоящий центрированный плеер

Пользователь явно подтвердил вариант «настоящий видеоплеер по центру — со звуком, Play и перемоткой, но со служебной строкой GitHub». Требование удаления filename из P10.7 уточнено этим решением: native header теперь **ACCEPTED_USER_NATIVE_PLAYER**, GIF не нужен. Прежние записи и отклонённая визуальная приёмка сохраняются как история.

README содержит центрированный компактный контейнер `table align="center"` / `td width="448"`, один настоящий MP4-плеер с controls; ссылка не уводит пользователя с README. Видео 448×432,43,535с,H.264/audio1 остаётся прежним attachment, новая загрузка не выполнялась. Хеш текущего README совпадает с проверенным P10.7 renderer/anonymous media200/Range206. [Уточнённый receipt](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-centered/source-checks-native-approved.json). Девять badges остаются непосредственно под platform line, заголовок «Технологии» отсутствует. Browser/CUA **NOT_DONE_USER_STOPPED**; HTML/HTTP не объявляются визуальным browser acceptance.

Root Git lease и owned4paths подтверждены; соседняя сохранённая Web session уведомлена `msg_51964f941966`, source frozen. Base `2d71bffb4c2a14f6e102fe24c166d96f6356e977`, branch `mac`, index был пуст; foreign design drafts сохранены. Commit/push/actual public README/CI **PENDING** на момент записи. Окончательные результаты и exact resume сохраняются в [ROOT-PROGRESS.md](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-centered/ROOT-PROGRESS.md). Эта итерация меняет README и журналы; приложение, сайт, release/DB assets не меняются.


### 2026-10-10T18:47:09.395111+00:00 — P10.9 — новый steering: GIF во всю ширину

До commit/push пользователь уточнил: «не пусть будет как гиф только по всей области вот этого экрана». Решение P10.8 о native player отменено текущим steering; прежняя история сохранена. Итоговый контракт этой итерации: GIF из всей настоящей записи, полная ширина README, исходные пропорции без обрезки, без filename-панели GitHub и пустой области справа. GIF автоматически повторяется, звук и controls отсутствуют по выбранному формату.

![Пользовательский screenshot: область для полного заполнения GIF](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/user-feedback-full-width.png)

Это screenshot пользователя, не новая computer-use проверка. SHA256 4a955eb2dac4db87dea9b47424bb8d43f643e91df77bcd411fdca0c8e8cc2031. GitHub renderer проверен для plain img, пустого anchor и picture: первые два автоматически получают ссылку на файл, `picture` сохраняет img без ссылки. В README выбран `picture` с `width="100%"`; контейнер448px и native attachment удалены. Полный source MP4 не меняется. Для конверсии используются временные uv-tools, зависимости проекта не добавляются; крупные промежуточные GIF заменяются, в repo остаётся один окончательный файл.

Root owns5paths: README.md, docs/assets/translator-demo.gif и три presentation journals. Сосед Web уведомлён msg_0cb7b1ab3823; site/app/release/DB untouched. Source/decoder/HTTP acceptance и доставка **PENDING** на момент этой записи; browser/CUA остаются NOT_DONE_USER_STOPPED. Следующий шаг — оптимизированный GIF, scoped acceptance, normal named commit/helper push/actual public README/CI. Exact resume: `cd '/Users/den/Documents/dev/selection_translator_anki' && codex resume '01a1030e-0fcc-7430-8c9d-070c3f569b23'`.


### 2026-10-10T18:50:18.359112+00:00 — P10.10 — GIF source/renderer/HTTP acceptance

Окончательный GIF `docs/assets/translator-demo.gif`: 672×648,6fps,261frames,43,5с,15 531 836bytes,SHA256 `21041668284ebde97097bc2c95306a15c9ba12d802ace43bc19917088b74e14a`. Вся исходная визуальная запись сохранена без обрезки; пропорции точно совпадают с1120×1080 исходника. GIF loop0, каждый frame декодирован, composite полностью opaque во всех кадрах. MP4 source SHA256 `2f9df652afa0668c9a4cb3eb6d7860d2407a46657206171f9c94bd9858a8cbb2` неизменён. Более крупные промежуточные GIF85/84/38МБ не коммитились и заменены единственным окончательным файлом; trials сохранены как small metadata/log receipts вне repo.

Лично просмотрены три кадра GIF — начало, середина и конец: содержимое настоящей записи и текст читаются. Это derived frames из записи пользователя, **не screenshots новой runtime/browser проверки**:

![Начало настоящей записи](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/gif-preview-0.png)

![Середина настоящей записи](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/gif-preview-130.png)

![Конец настоящей записи](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/gif-preview-260.png)

`uv run --no-project python .../readme-gif/check_readme.py` exit0: actual GitHub renderer содержит один GIF в picture с width100%, без anchor/video/details/filename;9badges прямо под platform line, «Технологии» отсутствует. Два local HTTP GET root/subpath дали200,image/gif,точные bytes/SHA; временный сервер остановлен. Scoped diff-check/base ancestry PASS. [Source checks](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/source-checks.json), [GIF metadata](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/gif-metadata.json). Dependencies проекта не менялись.

Source/renderer/HTTP **PASS**; browser/CUA **NOT_DONE_USER_STOPPED**. Five owned paths staged/commit/push/public/CI ещё **PENDING**; результаты фиксируются после выполнения в [ROOT-PROGRESS.md](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-gif/ROOT-PROGRESS.md). Чужие design drafts и source сайта/приложения/release/DB сохранены.


### 2026-10-10T19:27:56.925734+00:00 — P10.11 — точный пользовательский MP4 вместо отклонённого GIF

Пользователь отклонил GIF из P10.10: «ужасно лагающая» демонстрация, и прямо указал `translator_demo_gif.mp4`. Визуальная приёмка предыдущего GIF — **FAIL_USER_REPORT**; исторические source/HTTP/CI PASS не доказывают качество движения. GIF был уменьшен до 6 fps; этот выбор давал дискретное движение. Новый критерий: использовать переданный MP4 без перекодирования, обрезки и уменьшения частоты кадров. История выше сохранена.

Источник `/Users/den/Documents/obs/translator_demo_gif.mp4`: H.264, 1120×1080, 60 fps, 43,483333 с, 2609 кадров, без звуковой дорожки; 15 107 313 bytes, SHA256 `c81e56cc5402910aa58c813c526346ff32ca64fc50a660e5c3dc5ce1e4d4c8d1`. **PASS_SOURCE_DECODE**: все кадры декодированы; исходный файл не изменён. **PASS_UPLOAD_RENDER_HTTP**: [точный attachment](https://github.com/user-attachments/assets/1d40c4a2-1794-4447-b1a3-518d374e3714) через standalone GitHub uploader без issue/comment/PR; анонимный renderer содержит один native video с controls, без ссылки вокруг видео; HTTP200/video/mp4, bytes/SHA совпадают с оригиналом; Range206 возвращает точные первые1024bytes. [Source receipt](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-user-mp4/source-checks.json).

README использует `table align="center"`, `td width="664"`: эти атрибуты сохранены GitHub renderer. Ширина выбрана по соотношению1120/1080 при GitHub `max-height:640px`. GitHub сохраняет служебную строку имени файла и Play/перемотку, удаляет autoplay/loop: GIF-подобное автоматическое повторение MP4 в README этим renderer не поддерживается. **NOT_DONE_USER_STOPPED**: browser/CUA, ручной Play, фактические viewport geometry/плавность не объявлены проверенными. Новый файл не содержит аудио, поэтому звук не обещается.

Отклонённый `docs/assets/translator-demo.gif` удалён. Девять badges под platform line и download/DB links сохранены. Owned5paths: README.md, удаление GIF, эти три presentation журнала. Base `4833703f2063127b7d976a3e7d211a78e9e43653`, branch mac, исходный index пуст. Web уведомлён `msg_582759614e6f`; site frozen, чужие design drafts сохранены. Commit/push/remote/public README/CI фиксируются после запуска в [ROOT-PROGRESS.md](/Users/den/Documents/dev/translator-evidence/2026-10-10/readme-user-mp4/ROOT-PROGRESS.md); на момент этой source-записи **PENDING_DELIVERY**. Приложение, release artifacts и SQLite не меняются.
