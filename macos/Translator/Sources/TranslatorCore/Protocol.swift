import Foundation

// Mirror of `desktop_app/platform/macos/ipc/protocol.py` (the source of truth).
// Transport: Unix domain socket, newline-delimited JSON. Requests carry id/method/params;
// responses echo id with ok + result | error; events carry event + payload and no id.

public enum IPCMethod {
    public static let ping = "ping"
    public static let translate = "translate"
    public static let cancel = "cancel"
    public static let close = "close"
    public static let historyList = "history.list"
    public static let historySelect = "history.select"
    public static let examplesRefresh = "examples.refresh"
    public static let copyAll = "copy_all"
    public static let ankiStatus = "anki.status"
    public static let ankiDecks = "anki.decks"
    public static let ankiSelectDeck = "anki.select_deck"
    public static let ankiCreateModel = "anki.create_model"
    public static let ankiPrepareUpsert = "anki.prepare_upsert"
    public static let ankiApplyUpsert = "anki.apply_upsert"
    public static let settingsGet = "settings.get"
    public static let settingsSave = "settings.save"
    public static let shutdown = "shutdown"
}

public enum IPCEventName {
    public static let translationState = "translation.state"
    public static let notification = "notification"
    public static let ankiAvailability = "anki.availability"
    /// Synthesised by the client when the socket closes; never sent by the backend.
    public static let disconnected = "_client.disconnected"
}

public enum TranslationPhase: String, Codable, Sendable {
    case begin, partial, final, error, examples
}

// MARK: - Coding

public enum IPCCoding {
    public static let decoder: JSONDecoder = {
        let decoder = JSONDecoder()
        decoder.keyDecodingStrategy = .convertFromSnakeCase
        return decoder
    }()

    public static let encoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.keyEncodingStrategy = .convertToSnakeCase
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }()

    /// Verbatim keys. Used where unknown keys must survive a round trip, since
    /// `convertFromSnakeCase` then `convertToSnakeCase` is lossy (`a_bc` -> `aBC` -> `a_bc`
    /// holds, but `a_b_c` -> `aBC` -> `a_bc` does not).
    public static let plainDecoder = JSONDecoder()

    public static let plainEncoder: JSONEncoder = {
        let encoder = JSONEncoder()
        encoder.outputFormatting = [.sortedKeys, .withoutEscapingSlashes]
        return encoder
    }()
}

extension KeyedDecodingContainer {
    func value<T: Decodable>(_ type: T.Type, _ key: Key, default fallback: T) -> T {
        (try? decodeIfPresent(type, forKey: key)) ?? fallback
    }

    func optional<T: Decodable>(_ type: T.Type, _ key: Key) -> T? {
        try? decodeIfPresent(type, forKey: key)
    }
}

// MARK: - View state

public struct ExampleItem: Codable, Equatable, Hashable, Sendable {
    public var en: String

    public init(en: String) { self.en = en }
}

public struct ExamplePair: Codable, Equatable, Hashable, Sendable {
    public var en: String
    public var ru: String

    public init(en: String, ru: String) {
        self.en = en
        self.ru = ru
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        en = c.value(String.self, .en, default: "")
        ru = c.value(String.self, .ru, default: "")
    }
}

/// Dictionary-grade data from on-device engines (optional `apple` block of a ViewState).
public struct AppleSense: Codable, Equatable, Hashable, Sendable {
    public var index: Int
    public var label: String
    public var translation: String
    public var examples: [ExamplePair]

    public init(index: Int, label: String = "", translation: String, examples: [ExamplePair] = []) {
        self.index = index
        self.label = label
        self.translation = translation
        self.examples = examples
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        index = c.value(Int.self, .index, default: 0)
        label = c.value(String.self, .label, default: "")
        translation = c.value(String.self, .translation, default: "")
        examples = c.value([ExamplePair].self, .examples, default: [])
    }
}

public struct AppleEntry: Codable, Equatable, Hashable, Sendable {
    public var pos: String
    public var senses: [AppleSense]

    public init(pos: String, senses: [AppleSense]) {
        self.pos = pos
        self.senses = senses
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        pos = c.value(String.self, .pos, default: "")
        senses = c.value([AppleSense].self, .senses, default: [])
    }
}

public struct AppleLexical: Codable, Equatable, Hashable, Sendable {
    public var headword: String
    public var ipaUk: String
    public var ipaUs: String
    /// Flat POS label (older payload shape) — kept for compatibility.
    public var pos: String
    /// Flat senses (older payload shape).
    public var senses: [AppleSense]
    /// Grouped by part of speech (current payload shape).
    public var entries: [AppleEntry]

    public init(
        headword: String = "",
        ipaUk: String = "",
        ipaUs: String = "",
        pos: String = "",
        senses: [AppleSense] = [],
        entries: [AppleEntry] = []
    ) {
        self.headword = headword
        self.ipaUk = ipaUk
        self.ipaUs = ipaUs
        self.pos = pos
        self.senses = senses
        self.entries = entries
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        headword = c.value(String.self, .headword, default: "")
        ipaUk = c.value(String.self, .ipaUk, default: "")
        ipaUs = c.value(String.self, .ipaUs, default: "")
        pos = c.value(String.self, .pos, default: "")
        senses = c.value([AppleSense].self, .senses, default: [])
        entries = c.value([AppleEntry].self, .entries, default: [])
    }

    /// Entries regardless of which payload shape arrived.
    public var groupedEntries: [AppleEntry] {
        if !entries.isEmpty { return entries }
        if !senses.isEmpty { return [AppleEntry(pos: pos, senses: senses)] }
        return []
    }

    public var hasContent: Bool {
        !ipaUk.isEmpty || !ipaUs.isEmpty || !groupedEntries.isEmpty
    }
}

public struct ViewState: Codable, Equatable, Hashable, Sendable {
    public var original: String
    public var originalRaw: String
    public var translation: String
    public var definitionsItems: [String]
    public var examples: [ExampleItem]
    public var canRefreshExamples: Bool
    public var refreshingExamples: Bool
    public var loading: Bool
    public var canAddAnki: Bool
    public var entryId: Int?
    public var apple: AppleLexical?

    public init(
        original: String = "",
        originalRaw: String = "",
        translation: String = "",
        definitionsItems: [String] = [],
        examples: [ExampleItem] = [],
        canRefreshExamples: Bool = false,
        refreshingExamples: Bool = false,
        loading: Bool = false,
        canAddAnki: Bool = false,
        entryId: Int? = nil,
        apple: AppleLexical? = nil
    ) {
        self.original = original
        self.originalRaw = originalRaw
        self.translation = translation
        self.definitionsItems = definitionsItems
        self.examples = examples
        self.canRefreshExamples = canRefreshExamples
        self.refreshingExamples = refreshingExamples
        self.loading = loading
        self.canAddAnki = canAddAnki
        self.entryId = entryId
        self.apple = apple
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        original = c.value(String.self, .original, default: "")
        originalRaw = c.value(String.self, .originalRaw, default: "")
        translation = c.value(String.self, .translation, default: "")
        definitionsItems = c.value([String].self, .definitionsItems, default: [])
        examples = c.value([ExampleItem].self, .examples, default: [])
        canRefreshExamples = c.value(Bool.self, .canRefreshExamples, default: false)
        refreshingExamples = c.value(Bool.self, .refreshingExamples, default: false)
        loading = c.value(Bool.self, .loading, default: false)
        canAddAnki = c.value(Bool.self, .canAddAnki, default: false)
        entryId = c.optional(Int.self, .entryId)
        apple = c.optional(AppleLexical.self, .apple)
    }

    public var hasTranslation: Bool { !translation.isEmpty }
    public var isEmpty: Bool { original.isEmpty && translation.isEmpty }
}

// MARK: - Responses

public struct PingInfo: Codable, Equatable, Sendable {
    public struct Database: Codable, Equatable, Sendable {
        public var primary: Bool
        public var fallback: Bool
        public var definitions: Bool
        public var dir: String

        public init(primary: Bool = false, fallback: Bool = false, definitions: Bool = false, dir: String = "") {
            self.primary = primary
            self.fallback = fallback
            self.definitions = definitions
            self.dir = dir
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            primary = c.value(Bool.self, .primary, default: false)
            fallback = c.value(Bool.self, .fallback, default: false)
            definitions = c.value(Bool.self, .definitions, default: false)
            dir = c.value(String.self, .dir, default: "")
        }
    }

    public struct Engines: Codable, Equatable, Sendable {
        public var appleDictionary: Bool
        public var appleTranslation: Bool

        public init(appleDictionary: Bool = false, appleTranslation: Bool = false) {
            self.appleDictionary = appleDictionary
            self.appleTranslation = appleTranslation
        }

        public init(from decoder: Decoder) throws {
            let c = try decoder.container(keyedBy: CodingKeys.self)
            appleDictionary = c.value(Bool.self, .appleDictionary, default: false)
            appleTranslation = c.value(Bool.self, .appleTranslation, default: false)
        }
    }

    public var version: String
    public var protocolVersion: Int
    public var pid: Int
    public var platform: String
    public var db: Database
    public var engines: Engines

    enum CodingKeys: String, CodingKey {
        case version, pid, platform, db, engines
        case protocolVersion = "protocol"
    }

    public init(
        version: String = "",
        protocolVersion: Int = 0,
        pid: Int = 0,
        platform: String = "",
        db: Database = Database(),
        engines: Engines = Engines()
    ) {
        self.version = version
        self.protocolVersion = protocolVersion
        self.pid = pid
        self.platform = platform
        self.db = db
        self.engines = engines
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        version = c.value(String.self, .version, default: "")
        protocolVersion = c.value(Int.self, .protocolVersion, default: 0)
        pid = c.value(Int.self, .pid, default: 0)
        platform = c.value(String.self, .platform, default: "")
        db = c.value(Database.self, .db, default: Database())
        engines = c.value(Engines.self, .engines, default: Engines())
    }
}

public struct TranslateResponse: Codable, Equatable, Sendable {
    public var requestId: Int
    public var state: ViewState

    public init(requestId: Int, state: ViewState) {
        self.requestId = requestId
        self.state = state
    }
}

public struct HistoryItem: Codable, Equatable, Hashable, Identifiable, Sendable {
    public var entryId: Int
    public var text: String
    public var lookupText: String
    public var translation: String
    public var definitionsEn: [String]
    public var examples: [String]

    public var id: Int { entryId }

    public init(
        entryId: Int,
        text: String,
        lookupText: String = "",
        translation: String,
        definitionsEn: [String] = [],
        examples: [String] = []
    ) {
        self.entryId = entryId
        self.text = text
        self.lookupText = lookupText
        self.translation = translation
        self.definitionsEn = definitionsEn
        self.examples = examples
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        entryId = try c.decode(Int.self, forKey: .entryId)
        text = c.value(String.self, .text, default: "")
        lookupText = c.value(String.self, .lookupText, default: "")
        translation = c.value(String.self, .translation, default: "")
        definitionsEn = c.value([String].self, .definitionsEn, default: [])
        examples = c.value([String].self, .examples, default: [])
    }
}

public struct HistoryListResponse: Codable, Equatable, Sendable {
    public var items: [HistoryItem]

    public init(items: [HistoryItem]) { self.items = items }
}

public struct ExamplesRefreshResponse: Codable, Equatable, Sendable {
    public var requestId: Int?
    public var state: ViewState
    public var changed: Bool

    public init(requestId: Int? = nil, state: ViewState, changed: Bool) {
        self.requestId = requestId
        self.state = state
        self.changed = changed
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requestId = c.optional(Int.self, .requestId)
        state = c.value(ViewState.self, .state, default: ViewState())
        changed = c.value(Bool.self, .changed, default: false)
    }
}

public struct CopyAllResponse: Codable, Equatable, Sendable {
    public var text: String

    public init(text: String) { self.text = text }
}

public struct AnkiStatus: Codable, Equatable, Sendable {
    public var modelStatus: String
    public var deckStatus: String
    public var deckName: String
    public var available: Bool

    public init(modelStatus: String = "", deckStatus: String = "", deckName: String = "", available: Bool = false) {
        self.modelStatus = modelStatus
        self.deckStatus = deckStatus
        self.deckName = deckName
        self.available = available
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        modelStatus = c.value(String.self, .modelStatus, default: "")
        deckStatus = c.value(String.self, .deckStatus, default: "")
        deckName = c.value(String.self, .deckName, default: "")
        available = c.value(Bool.self, .available, default: false)
    }
}

public struct AnkiDecksResponse: Codable, Equatable, Sendable {
    public var decks: [String]
    public var error: String?

    public init(decks: [String], error: String? = nil) {
        self.decks = decks
        self.error = error
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        decks = c.value([String].self, .decks, default: [])
        error = c.optional(String.self, .error)
    }
}

public struct ActionResult: Codable, Equatable, Sendable {
    public var message: String
    public var modelStatus: String?
    public var deckStatus: String?
    public var deckName: String?

    public init(message: String, modelStatus: String? = nil, deckStatus: String? = nil, deckName: String? = nil) {
        self.message = message
        self.modelStatus = modelStatus
        self.deckStatus = deckStatus
        self.deckName = deckName
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        message = c.value(String.self, .message, default: "")
        modelStatus = c.optional(String.self, .modelStatus)
        deckStatus = c.optional(String.self, .deckStatus)
        deckName = c.optional(String.self, .deckName)
    }
}

public struct UpsertValues: Codable, Equatable, Sendable {
    public var translations: [String]
    public var definitionsEn: [String]
    public var examplesEn: [String]
    public var imagePath: String?

    public init(translations: [String] = [], definitionsEn: [String] = [], examplesEn: [String] = [], imagePath: String? = nil) {
        self.translations = translations
        self.definitionsEn = definitionsEn
        self.examplesEn = examplesEn
        self.imagePath = imagePath
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        translations = c.value([String].self, .translations, default: [])
        definitionsEn = c.value([String].self, .definitionsEn, default: [])
        examplesEn = c.value([String].self, .examplesEn, default: [])
        imagePath = c.optional(String.self, .imagePath)
    }
}

public struct UpsertMatch: Codable, Equatable, Hashable, Identifiable, Sendable {
    enum CodingKeys: String, CodingKey {
        case noteId, word, translation, definitionsEn, examplesEn, image
    }

    public var noteId: Int
    public var word: String
    public var translation: String
    public var definitionsEn: String
    public var examplesEn: String
    public var image: String?

    public var id: Int { noteId }

    public init(noteId: Int, word: String, translation: String, definitionsEn: String = "", examplesEn: String = "", image: String? = nil) {
        self.noteId = noteId
        self.word = word
        self.translation = translation
        self.definitionsEn = definitionsEn
        self.examplesEn = examplesEn
        self.image = image
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        noteId = try c.decode(Int.self, forKey: .noteId)
        word = c.value(String.self, .word, default: "")
        translation = c.value(String.self, .translation, default: "")
        definitionsEn = Self.text(c, .definitionsEn)
        examplesEn = Self.text(c, .examplesEn)
        image = c.optional(String.self, .image)
    }

    /// Backend may send either a joined string or a list for these fields.
    private static func text(_ c: KeyedDecodingContainer<CodingKeys>, _ key: CodingKeys) -> String {
        if let s = try? c.decodeIfPresent(String.self, forKey: key) { return s }
        if let list = try? c.decodeIfPresent([String].self, forKey: key) { return list.joined(separator: "; ") }
        return ""
    }
}

public struct UpsertPreview: Codable, Equatable, Sendable {
    public var values: UpsertValues
    public var matches: [UpsertMatch]
    public var availableFields: [String]

    public init(values: UpsertValues, matches: [UpsertMatch] = [], availableFields: [String] = []) {
        self.values = values
        self.matches = matches
        self.availableFields = availableFields
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        values = c.value(UpsertValues.self, .values, default: UpsertValues())
        matches = c.value([UpsertMatch].self, .matches, default: [])
        availableFields = c.value([String].self, .availableFields, default: [])
    }
}

public struct UpsertPreviewResponse: Codable, Equatable, Sendable {
    public var preview: UpsertPreview

    public init(preview: UpsertPreview) { self.preview = preview }
}

public enum FieldAction: String, Codable, CaseIterable, Sendable {
    case keepExisting = "keep_existing"
    case replaceWithSelected = "replace_with_selected"
    case mergeUniqueSelected = "merge_unique_selected"

    public var title: String {
        switch self {
        case .keepExisting: return "Keep existing"
        case .replaceWithSelected: return "Replace"
        case .mergeUniqueSelected: return "Merge"
        }
    }
}

public enum ImageAction: String, Codable, CaseIterable, Sendable {
    case keepExisting = "keep_existing"
    case replaceWithSelected = "replace_with_selected"

    public var title: String {
        switch self {
        case .keepExisting: return "Keep existing"
        case .replaceWithSelected: return "Replace"
        }
    }
}

public struct UpsertDecision: Codable, Equatable, Sendable {
    public var createNew: Bool
    public var targetNoteIds: [Int]
    public var translationAction: FieldAction
    public var definitionsAction: FieldAction
    public var examplesAction: FieldAction
    public var imageAction: ImageAction
    public var selectedTranslations: [String]
    public var selectedDefinitionsEn: [String]
    public var selectedExamplesEn: [String]
    public var imagePath: String?

    public init(
        createNew: Bool,
        targetNoteIds: [Int] = [],
        translationAction: FieldAction = .mergeUniqueSelected,
        definitionsAction: FieldAction = .mergeUniqueSelected,
        examplesAction: FieldAction = .mergeUniqueSelected,
        imageAction: ImageAction = .keepExisting,
        selectedTranslations: [String] = [],
        selectedDefinitionsEn: [String] = [],
        selectedExamplesEn: [String] = [],
        imagePath: String? = nil
    ) {
        self.createNew = createNew
        self.targetNoteIds = targetNoteIds
        self.translationAction = translationAction
        self.definitionsAction = definitionsAction
        self.examplesAction = examplesAction
        self.imageAction = imageAction
        self.selectedTranslations = selectedTranslations
        self.selectedDefinitionsEn = selectedDefinitionsEn
        self.selectedExamplesEn = selectedExamplesEn
        self.imagePath = imagePath
    }

    /// JSON object for the `decision` param (snake_case keys, `image_path` explicit null).
    public func jsonObject() throws -> [String: Any] {
        let data = try IPCCoding.encoder.encode(self)
        guard var object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw CocoaError(.coderInvalidValue)
        }
        if object["image_path"] == nil { object["image_path"] = NSNull() }
        return object
    }
}

public struct UpsertOutcome: Codable, Equatable, Sendable {
    public var outcome: String
    public var message: String

    public init(outcome: String, message: String) {
        self.outcome = outcome
        self.message = message
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        outcome = c.value(String.self, .outcome, default: "error")
        message = c.value(String.self, .message, default: "")
    }

    public var isSuccess: Bool { outcome == "success" || outcome == "updated" }
}

// MARK: - Settings (mirror of desktop_app.config.config_to_dict)

public struct LanguageSettings: Codable, Equatable, Sendable {
    enum CodingKeys: String, CodingKey {
        case source, target
    }

    public var source: String
    public var target: String

    public init(source: String = "en", target: String = "ru") {
        self.source = source
        self.target = target
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        source = c.value(String.self, .source, default: "en")
        target = c.value(String.self, .target, default: "ru")
    }
}

public struct AnkiFieldMapping: Codable, Equatable, Sendable {
    enum CodingKeys: String, CodingKey {
        case word, translation, image
        case exampleEn = "example_en"
        case definitionsEn = "definitions_en"
    }

    public var word: String
    public var translation: String
    public var exampleEn: String
    public var definitionsEn: String
    public var image: String

    public init(word: String = "Word", translation: String = "Translation", exampleEn: String = "Example", definitionsEn: String = "Definitions", image: String = "Image") {
        self.word = word
        self.translation = translation
        self.exampleEn = exampleEn
        self.definitionsEn = definitionsEn
        self.image = image
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        word = c.value(String.self, .word, default: "")
        translation = c.value(String.self, .translation, default: "")
        exampleEn = c.value(String.self, .exampleEn, default: "")
        definitionsEn = c.value(String.self, .definitionsEn, default: "")
        image = c.value(String.self, .image, default: "")
    }
}

public struct AnkiSettings: Codable, Equatable, Sendable {
    enum CodingKeys: String, CodingKey {
        case deck, model, fields
    }

    public var deck: String
    public var model: String
    public var fields: AnkiFieldMapping

    public init(deck: String = "", model: String = "", fields: AnkiFieldMapping = AnkiFieldMapping()) {
        self.deck = deck
        self.model = model
        self.fields = fields
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        deck = c.value(String.self, .deck, default: "")
        model = c.value(String.self, .model, default: "")
        fields = c.value(AnkiFieldMapping.self, .fields, default: AnkiFieldMapping())
    }
}

public struct BackendSettings: Codable, Equatable, Sendable {
    public var languages: LanguageSettings
    public var anki: AnkiSettings
    /// Keys we do not model are preserved verbatim so `settings.save` never drops them.
    public var extra: [String: JSONValue]

    enum CodingKeys: String, CodingKey {
        case languages, anki
    }

    public init(languages: LanguageSettings = LanguageSettings(), anki: AnkiSettings = AnkiSettings(), extra: [String: JSONValue] = [:]) {
        self.languages = languages
        self.anki = anki
        self.extra = extra
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        languages = c.value(LanguageSettings.self, .languages, default: LanguageSettings())
        anki = c.value(AnkiSettings.self, .anki, default: AnkiSettings())
        let all = try decoder.container(keyedBy: JSONValue.DynamicKey.self)
        var extra: [String: JSONValue] = [:]
        for key in all.allKeys where key.stringValue != "languages" && key.stringValue != "anki" {
            if let value = try? all.decode(JSONValue.self, forKey: key) {
                extra[key.stringValue] = value
            }
        }
        self.extra = extra
    }

    public func encode(to encoder: Encoder) throws {
        var c = encoder.container(keyedBy: CodingKeys.self)
        try c.encode(languages, forKey: .languages)
        try c.encode(anki, forKey: .anki)
        var dynamic = encoder.container(keyedBy: JSONValue.DynamicKey.self)
        for (key, value) in extra {
            try dynamic.encode(value, forKey: JSONValue.DynamicKey(stringValue: key))
        }
    }

    /// Decode a `settings.get` result. Keys are read verbatim, so unmodelled ones survive.
    public static func decode(from data: Data) throws -> BackendSettings {
        try IPCCoding.plainDecoder.decode(BackendSettings.self, from: data)
    }

    /// JSON object for the `config` param of `settings.save`.
    public func jsonObject() throws -> [String: Any] {
        let data = try IPCCoding.plainEncoder.encode(self)
        guard let object = try JSONSerialization.jsonObject(with: data) as? [String: Any] else {
            throw CocoaError(.coderInvalidValue)
        }
        return object
    }
}

// MARK: - Events

public struct TranslationStateEvent: Codable, Equatable, Sendable {
    public var requestId: Int
    public var phase: TranslationPhase
    public var state: ViewState

    public init(requestId: Int, phase: TranslationPhase, state: ViewState) {
        self.requestId = requestId
        self.phase = phase
        self.state = state
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        requestId = c.value(Int.self, .requestId, default: 0)
        phase = c.value(TranslationPhase.self, .phase, default: .partial)
        state = c.value(ViewState.self, .state, default: ViewState())
    }
}

public enum NotificationLevel: String, Codable, Sendable {
    case success, info, warning, error
}

public struct NotificationEvent: Codable, Equatable, Sendable {
    public var message: String
    public var level: NotificationLevel

    public init(message: String, level: NotificationLevel) {
        self.message = message
        self.level = level
    }

    public init(from decoder: Decoder) throws {
        let c = try decoder.container(keyedBy: CodingKeys.self)
        message = c.value(String.self, .message, default: "")
        level = c.value(NotificationLevel.self, .level, default: .info)
    }
}

public struct AnkiAvailabilityEvent: Codable, Equatable, Sendable {
    public var available: Bool

    public init(available: Bool) { self.available = available }
}

// MARK: - Generic JSON value (for settings passthrough)

public enum JSONValue: Codable, Equatable, Sendable {
    case string(String)
    case number(Double)
    case bool(Bool)
    case null
    case array([JSONValue])
    case object([String: JSONValue])

    public struct DynamicKey: CodingKey {
        public var stringValue: String
        public var intValue: Int? { nil }
        public init(stringValue: String) { self.stringValue = stringValue }
        public init?(intValue: Int) { return nil }
    }

    public init(from decoder: Decoder) throws {
        let single = try decoder.singleValueContainer()
        if single.decodeNil() {
            self = .null
        } else if let b = try? single.decode(Bool.self) {
            self = .bool(b)
        } else if let n = try? single.decode(Double.self) {
            self = .number(n)
        } else if let s = try? single.decode(String.self) {
            self = .string(s)
        } else if let a = try? single.decode([JSONValue].self) {
            self = .array(a)
        } else if let o = try? single.decode([String: JSONValue].self) {
            self = .object(o)
        } else {
            throw DecodingError.dataCorruptedError(in: single, debugDescription: "unsupported JSON value")
        }
    }

    public func encode(to encoder: Encoder) throws {
        var single = encoder.singleValueContainer()
        switch self {
        case .null: try single.encodeNil()
        case let .bool(b): try single.encode(b)
        case let .number(n):
            if n == n.rounded(), abs(n) < 1e15 { try single.encode(Int(n)) } else { try single.encode(n) }
        case let .string(s): try single.encode(s)
        case let .array(a): try single.encode(a)
        case let .object(o): try single.encode(o)
        }
    }
}
