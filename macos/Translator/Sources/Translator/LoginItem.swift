import Foundation
import ServiceManagement
import TranslatorCore

/// Whether this app opens itself at login.
///
/// The backend already starts at login through its launchd agent, and that made the gap
/// hard to see: after a restart the daemon answered, the databases were open, and the
/// install looked healthy — while the shortcut, the popup and Settings all live in this
/// process and none of them existed until someone opened the app by hand.
///
/// `SMAppService` is asked for the state rather than the background-task database: the
/// dump tool hangs on this machine, and the API also distinguishes "not registered" from
/// "waiting for the user to approve it", which the stage has to say out loud.
enum LoginItem {
    static var state: LoginItemState {
        switch SMAppService.mainApp.status {
        case .enabled: return .enabled
        case .requiresApproval: return .requiresApproval
        // Measured, not assumed: an app that has never been registered answers
        // `.notFound`, and registering it from that state succeeds. Reading it as "the
        // system cannot find this bundle" would leave every fresh install looking at a
        // stage with no button.
        case .notRegistered, .notFound: return .notRegistered
        @unknown default: return .unavailable
        }
    }

    static func enable() throws { try SMAppService.mainApp.register() }

    static func disable() throws { try SMAppService.mainApp.unregister() }

    /// Approval lives in System Settings and is the user's to give; the app can only
    /// bring them to it.
    static func openSettings() { SMAppService.openSystemSettingsLoginItems() }
}
