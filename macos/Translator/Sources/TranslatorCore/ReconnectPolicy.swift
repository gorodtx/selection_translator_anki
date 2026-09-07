import Foundation

/// How long to wait between attempts to reach the backend socket.
///
/// The GNOME extension retries 40 times, 100 ms apart, because a D-Bus activation answers
/// almost at once. This backend does not: it starts a Python runtime, opens three SQLite
/// bases and warms the dictionary sidecar, which measured 6 to 14 seconds here. A four
/// second window therefore expires while a perfectly healthy backend is still starting,
/// and the client used to treat that as permanent failure.
///
/// So the burst stays — it makes an already-running backend appear instantly — and after
/// it there is a slower retry that never gives up, because the backend can come back at
/// any time and the user should not have to restart the app to notice.
public struct ReconnectPolicy: Equatable, Sendable {
    public let burstAttempts: Int
    public let burstDelay: TimeInterval
    public let idleDelay: TimeInterval
    public let maxIdleDelay: TimeInterval

    public init(
        burstAttempts: Int = 40,
        burstDelay: TimeInterval = 0.1,
        idleDelay: TimeInterval = 1.0,
        maxIdleDelay: TimeInterval = 5.0
    ) {
        self.burstAttempts = max(1, burstAttempts)
        self.burstDelay = max(0, burstDelay)
        self.idleDelay = max(0, idleDelay)
        self.maxIdleDelay = max(max(0, idleDelay), maxIdleDelay)
    }

    /// Wait before starting round `round` (1 is the first burst, which starts at once).
    ///
    /// Rounds back off so a backend that is simply absent costs nothing, while a backend
    /// that is restarting is picked up within a second.
    public func delayBeforeRound(_ round: Int) -> TimeInterval {
        guard round > 1 else { return 0 }
        let steps = min(round - 2, 3)
        let scaled = idleDelay * pow(2, Double(steps))
        return min(scaled, maxIdleDelay)
    }

    /// The message shown after a round failed. It has to read as "still trying".
    public func waitingMessage(socketPath: String) -> String {
        "Waiting for the backend at \(socketPath)"
    }
}
