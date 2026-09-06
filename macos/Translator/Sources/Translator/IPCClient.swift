import Darwin
import Foundation
import TranslatorCore

/// NDJSON client for the Python backend over a Unix domain socket.
///
/// One background thread owns the socket: it connects (retrying), reads frames, and feeds
/// them back. Requests are written from the caller's thread under a lock and completed by
/// `id`. Callbacks are delivered on the main actor, so the UI never marshals by hand.
final class IPCClient: @unchecked Sendable {
    enum ConnectionState: Equatable {
        case idle
        case connecting(attempt: Int)
        case connected
        case failed(String)
    }

    /// Matches the GNOME extension's retry shape: 40 attempts, 100 ms apart.
    static let retryLimit = 40
    static let retryDelay: TimeInterval = 0.1
    static let requestTimeout: TimeInterval = 30

    private let socketPath: String
    private let lock = NSLock()
    private var fd: Int32 = -1
    private var reader: Thread?
    private var nextId = 1
    private var pending: [String: (Result<Data, Error>) -> Void] = [:]
    private var stopping = false
    private var framer = LineFramer()

    var onEvent: (@MainActor (IPCEvent) -> Void)?
    var onStateChange: (@MainActor (ConnectionState) -> Void)?

    private(set) var state: ConnectionState = .idle {
        didSet {
            guard state != oldValue, let handler = onStateChange else { return }
            let value = state
            Task { @MainActor in handler(value) }
        }
    }

    init(socketPath: String) {
        self.socketPath = socketPath
    }

    static func defaultSocketPath() -> String {
        if let override = ProcessInfo.processInfo.environment["TRANSLATOR_SOCKET_PATH"], !override.isEmpty {
            return (override as NSString).expandingTildeInPath
        }
        let support = FileManager.default.urls(for: .applicationSupportDirectory, in: .userDomainMask).first
            ?? URL(fileURLWithPath: NSHomeDirectory()).appendingPathComponent("Library/Application Support")
        return support.appendingPathComponent("Translator/run/backend.sock").path
    }

    // MARK: - Lifecycle

    func start() {
        lock.lock()
        let alreadyRunning = reader != nil && !stopping
        stopping = false
        lock.unlock()
        guard !alreadyRunning else { return }
        let thread = Thread { [weak self] in self?.runLoop() }
        thread.name = "translator.ipc"
        thread.qualityOfService = .userInitiated
        lock.lock()
        reader = thread
        lock.unlock()
        thread.start()
    }

    func stop() {
        lock.lock()
        stopping = true
        let socket = fd
        fd = -1
        lock.unlock()
        if socket >= 0 { Darwin.close(socket) }
        failAllPending(IPCError(code: "disconnected", message: "Client stopped."))
    }

    var isConnected: Bool {
        lock.lock()
        defer { lock.unlock() }
        return fd >= 0
    }

    // MARK: - Requests

    /// Send a request and decode `result` as `T`.
    func send<T: Decodable>(_ method: String, params: [String: Any] = [:], as type: T.Type) async throws -> T {
        let data = try await sendRaw(method, params: params)
        if T.self == Empty.self { return Empty() as! T }
        return try IPCCoding.decoder.decode(T.self, from: data)
    }

    /// Send a request, ignoring the result payload.
    @discardableResult
    func send(_ method: String, params: [String: Any] = [:]) async throws -> Data {
        try await sendRaw(method, params: params)
    }

    private func sendRaw(_ method: String, params: [String: Any]) async throws -> Data {
        let id = nextRequestId()
        let frame = try IPCFraming.request(id: id, method: method, params: params)
        return try await withCheckedThrowingContinuation { continuation in
            let key = String(id)
            var resumed = false
            let finish: (Result<Data, Error>) -> Void = { result in
                guard !resumed else { return }
                resumed = true
                continuation.resume(with: result)
            }
            lock.lock()
            let socket = fd
            if socket < 0 {
                lock.unlock()
                finish(.failure(IPCError(code: "disconnected", message: "Backend is not connected.")))
                return
            }
            pending[key] = finish
            lock.unlock()

            if !Self.writeAll(socket, frame) {
                lock.lock(); pending.removeValue(forKey: key); lock.unlock()
                finish(.failure(IPCError(code: "write_failed", message: "Failed to write to backend.")))
                return
            }
            // Timeout guard so a wedged backend cannot leak continuations.
            DispatchQueue.global().asyncAfter(deadline: .now() + Self.requestTimeout) { [weak self] in
                guard let self else { return }
                self.lock.lock()
                let handler = self.pending.removeValue(forKey: key)
                self.lock.unlock()
                handler?(.failure(IPCError(code: "timeout", message: "\(method) timed out.")))
            }
        }
    }

    private func nextRequestId() -> Int {
        lock.lock()
        defer { lock.unlock() }
        let id = nextId
        nextId += 1
        return id
    }

    // MARK: - Socket thread

    private func runLoop() {
        while true {
            lock.lock(); let shouldStop = stopping; lock.unlock()
            if shouldStop { break }

            var socket: Int32 = -1
            for attempt in 1...Self.retryLimit {
                lock.lock(); let cancelled = stopping; lock.unlock()
                if cancelled { return }
                state = .connecting(attempt: attempt)
                socket = Self.connect(to: socketPath)
                if socket >= 0 { break }
                Thread.sleep(forTimeInterval: Self.retryDelay)
            }
            guard socket >= 0 else {
                state = .failed("Backend socket not available at \(socketPath)")
                return
            }
            lock.lock()
            fd = socket
            framer = LineFramer()
            lock.unlock()
            state = .connected

            readUntilClosed(socket)

            lock.lock()
            let wasStopping = stopping
            if fd == socket { fd = -1 }
            lock.unlock()
            Darwin.close(socket)
            failAllPending(IPCError(code: "disconnected", message: "Backend connection closed."))
            emit(IPCEvent(name: IPCEventName.disconnected, payload: Data("{}".utf8)))
            if wasStopping { return }
            state = .idle
            Thread.sleep(forTimeInterval: Self.retryDelay)
        }
    }

    private func readUntilClosed(_ socket: Int32) {
        var chunk = [UInt8](repeating: 0, count: 16 * 1024)
        while true {
            let count = chunk.withUnsafeMutableBytes { buffer in
                Darwin.recv(socket, buffer.baseAddress, buffer.count, 0)
            }
            if count > 0 {
                let data = Data(chunk[0..<count])
                lock.lock()
                let lines = framer.append(data)
                lock.unlock()
                for line in lines { handle(line: line) }
                continue
            }
            if count == 0 { return }               // peer closed
            if errno == EINTR { continue }
            return
        }
    }

    private func handle(line: Data) {
        guard let incoming = try? IPCFraming.parse(line: line) else { return }
        switch incoming {
        case let .response(response):
            lock.lock()
            let handler = pending.removeValue(forKey: response.id)
            lock.unlock()
            guard let handler else { return }
            if response.ok {
                handler(.success(response.result ?? Data("{}".utf8)))
            } else {
                handler(.failure(response.error ?? IPCError(code: "internal", message: "Request failed.")))
            }
        case let .event(event):
            emit(event)
        }
    }

    private func emit(_ event: IPCEvent) {
        guard let handler = onEvent else { return }
        Task { @MainActor in handler(event) }
    }

    private func failAllPending(_ error: Error) {
        lock.lock()
        let handlers = pending
        pending.removeAll()
        lock.unlock()
        for handler in handlers.values { handler(.failure(error)) }
    }

    // MARK: - POSIX helpers

    private static func connect(to path: String) -> Int32 {
        guard path.utf8.count < MemoryLayout.size(ofValue: sockaddr_un().sun_path) else { return -1 }
        let socket = Darwin.socket(AF_UNIX, SOCK_STREAM, 0)
        guard socket >= 0 else { return -1 }
        var address = sockaddr_un()
        address.sun_family = sa_family_t(AF_UNIX)
        let pathBytes = Array(path.utf8)
        withUnsafeMutableBytes(of: &address.sun_path) { raw in
            raw.copyBytes(from: pathBytes)
            raw[pathBytes.count] = 0
        }
        address.sun_len = UInt8(MemoryLayout<sockaddr_un>.size)
        let result = withUnsafePointer(to: &address) { pointer in
            pointer.withMemoryRebound(to: sockaddr.self, capacity: 1) { sockaddrPointer in
                Darwin.connect(socket, sockaddrPointer, socklen_t(MemoryLayout<sockaddr_un>.size))
            }
        }
        if result != 0 {
            Darwin.close(socket)
            return -1
        }
        var noSigPipe: Int32 = 1
        setsockopt(socket, SOL_SOCKET, SO_NOSIGPIPE, &noSigPipe, socklen_t(MemoryLayout<Int32>.size))
        return socket
    }

    private static func writeAll(_ socket: Int32, _ data: Data) -> Bool {
        var sent = 0
        return data.withUnsafeBytes { buffer -> Bool in
            guard let base = buffer.baseAddress else { return false }
            while sent < buffer.count {
                let written = Darwin.send(socket, base.advanced(by: sent), buffer.count - sent, 0)
                if written > 0 { sent += written; continue }
                if written < 0 && errno == EINTR { continue }
                return false
            }
            return true
        }
    }
}

/// Placeholder for methods whose result carries no fields.
struct Empty: Codable, Sendable {
    init() {}
}
