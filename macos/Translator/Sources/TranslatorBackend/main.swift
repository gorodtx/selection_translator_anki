import Foundation

// The backend runs at login, so whatever launchd starts appears in the user's Login
// Items. That used to be a shell script, and a script cannot carry a signature: the
// system could not tie it to this app and listed a bare "run-backend" from an
// unidentified developer — indistinguishable from something the user never installed.
// This is a Mach-O in Contents/MacOS, signed with the bundle, so the item is
// attributable to Translator and says what it belongs to.
//
// It does nothing but prepare the environment and hand the process over: launchd watches
// the pid it started, so replacing this process is right and spawning a child is not.

let executable = (Bundle.main.executableURL ?? URL(fileURLWithPath: CommandLine.arguments[0]))
    .resolvingSymlinksInPath()
let resources = executable
    .deletingLastPathComponent()  // Contents/MacOS
    .deletingLastPathComponent()  // Contents
    .appendingPathComponent("Resources")

func die(_ message: String, _ code: Int32) -> Never {
    FileHandle.standardError.write(Data("translator-backend: \(message)\n".utf8))
    // KeepAlive restarts on a non-zero exit, so a broken bundle retries on launchd's
    // throttle rather than looking like a backend that started and went quiet.
    exit(code)
}

// Executed through a link named after the app: Activity Monitor names a process after
// the file that was executed, and "python3.13" tells the user nothing about whose process
// it is or why it never stops. The link points at the same interpreter.
let python = resources.appendingPathComponent("bin/TranslatorEngine")
guard FileManager.default.isExecutableFile(atPath: python.path) else {
    die("no engine at \(python.path); the bundle is incomplete", 66)
}

setenv("PYTHONPATH", "\(resources.path)/app:\(resources.path)/site-packages", 1)
setenv("PYTHONDONTWRITEBYTECODE", "1", 1)
setenv("PYTHONUNBUFFERED", "1", 1)
setenv("TRANSLATOR_APPLE_HELPER", resources.appendingPathComponent("bin/TranslatorLookup").path, 1)

var argv: [UnsafeMutablePointer<CChar>?] = [
    strdup(python.path), strdup("-m"), strdup("desktop_app.platform.macos.daemon"),
]
argv += CommandLine.arguments.dropFirst().map { strdup($0) }
argv.append(nil)
execv(python.path, &argv)
die("could not start python: \(String(cString: strerror(errno)))", 71)
