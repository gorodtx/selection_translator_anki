import AppleLangHelperCore
import Foundation

// JSON-lines server over stdio. Reads one request per line, answers one line per request,
// exits on EOF or on an explicit `shutdown` op. Diagnostics go to stderr only.
//
// The main thread stays in `dispatchMain()`: Translation.framework and Dictionary Services
// deliver XPC replies through the main queue, so blocking it (semaphore, plain `while` loop)
// deadlocks the first system call. Requests are read on a dedicated thread and handled
// sequentially on the cooperative pool.
signal(SIGPIPE, SIG_IGN)

let dispatcher = Dispatcher()
let stdoutHandle = FileHandle.standardOutput
let outputLock = NSLock()

func emit(_ response: Response) {
    let line: String
    do {
        line = try response.jsonLine()
    } catch {
        line = "{\"id\":\"\(response.id)\",\"ok\":false,\"error\":{\"code\":\"internal\",\"message\":\"encoding failed\"}}"
    }
    outputLock.lock()
    stdoutHandle.write(Data((line + "\n").utf8))
    outputLock.unlock()
}

let reader = Thread {
    while let raw = readLine(strippingNewline: true) {
        let line = raw.trimmingCharacters(in: .whitespaces)
        if line.isEmpty { continue }
        let done = DispatchSemaphore(value: 0)
        var shouldExit = false
        Task.detached(priority: .userInitiated) {
            let response = await dispatcher.handle(line: line)
            emit(response)
            if case .shuttingDown = response.result { shouldExit = true }
            done.signal()
        }
        done.wait()
        if shouldExit { exit(0) }
    }
    exit(0)
}
reader.name = "apple-lang-helper.stdin"
reader.start()
dispatchMain()
