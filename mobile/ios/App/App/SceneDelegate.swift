// Native scene/Capacitor integration and same-origin offline recovery.
// The bundle contains neutral HTML/assets; account records stay in the existing
// encrypted WebView workspace. Preserve downstream navigation policy and keep
// authorization, certificate and failed POST responses visible. See mobile/README.md.
import UIKit
import Capacitor
import WebKit

class SceneDelegate: UIResponder, UIWindowSceneDelegate {
    var window: UIWindow?

    func scene(_ scene: UIScene, willConnectTo session: UISceneSession, options connectionOptions: UIScene.ConnectionOptions) {
        guard let windowScene = scene as? UIWindowScene else { return }

        window = UIWindow(windowScene: windowScene)
        window?.rootViewController = NurseBridgeViewController()
        window?.makeKeyAndVisible()

        SceneDelegateProxy.shared.scene(scene, willConnectTo: session, options: connectionOptions)
    }

    func scene(_ scene: UIScene, openURLContexts URLContexts: Set<UIOpenURLContext>) {
        SceneDelegateProxy.shared.scene(scene, openURLContexts: URLContexts)
    }

    func scene(_ scene: UIScene, continue userActivity: NSUserActivity) {
        SceneDelegateProxy.shared.scene(scene, continue: userActivity)
    }

    func sceneDidBecomeActive(_ scene: UIScene) {
        (window?.rootViewController as? NurseBridgeViewController)?.webView?
            .evaluateJavaScript("document.dispatchEvent(new Event('nurse:sync-request'))", completionHandler: nil)
    }
}

class NurseBridgeViewController: CAPBridgeViewController {
    private var offlineNavigation: NurseOfflineNavigation?

    override func capacitorDidLoad() {
        super.capacitorDidLoad()
        webView?.allowsBackForwardNavigationGestures = true
        guard let webView = webView, let origin = bridge?.config.serverURL,
              ["https", "http"].contains(origin.scheme ?? "") else { return }
        let navigation = NurseOfflineNavigation(webView: webView, origin: origin)
        offlineNavigation = navigation
        webView.navigationDelegate = navigation
    }
}

// Forward Capacitor's existing navigation policy and lifecycle callbacks. Only
// failed same-site GET navigation gains a bundled, same-origin fallback.
private class NurseOfflineNavigation: NSObject, WKNavigationDelegate {
    private weak var downstream: WKNavigationDelegate?
    private weak var webView: WKWebView?
    private let origin: URL
    private var loadingBundle = false
    private var request: URLRequest?
    private var startupTimeout: DispatchWorkItem?

    init(webView: WKWebView, origin: URL) {
        self.downstream = webView.navigationDelegate
        self.webView = webView
        self.origin = origin
        super.init()
        let timeout = DispatchWorkItem { [weak self] in self?.showOffline() }
        startupTimeout = timeout
        DispatchQueue.main.asyncAfter(deadline: .now() + 8, execute: timeout)
    }

    deinit { startupTimeout?.cancel() }

    override func responds(to selector: Selector!) -> Bool {
        super.responds(to: selector) || downstream?.responds(to: selector) == true
    }

    override func forwardingTarget(for selector: Selector!) -> Any? {
        if downstream?.responds(to: selector) == true { return downstream }
        return super.forwardingTarget(for: selector)
    }

    private func sameSite(_ url: URL?) -> Bool {
        guard let url = url else { return false }
        return url.scheme == origin.scheme && url.host == origin.host && url.port == origin.port
    }

    private var recoverable: Bool {
        !loadingBundle && request?.httpMethod == "GET" && sameSite(request?.url)
    }

    private func showOffline() {
        startupTimeout?.cancel()
        guard !loadingBundle, let webView = webView,
              let file = Bundle.main.url(forResource: "offline", withExtension: "html", subdirectory: "public"),
              let document = try? String(contentsOf: file, encoding: .utf8) else { return }
        loadingBundle = true
        webView.stopLoading()
        // Retain the remote site's security origin and persistent WKWebsiteDataStore.
        // No account data, cookies or keys are copied into the app bundle.
        let request = URLRequest(url: origin.appendingPathComponent("offline-shell"))
        webView.loadSimulatedRequest(request, responseHTML: document)
    }

    func webView(_ webView: WKWebView, decidePolicyFor action: WKNavigationAction,
                 decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
        if action.targetFrame?.isMainFrame == true { request = action.request }
        if downstream?.webView?(webView, decidePolicyFor: action, decisionHandler: decisionHandler) == nil {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, decidePolicyFor response: WKNavigationResponse,
                 decisionHandler: @escaping (WKNavigationResponsePolicy) -> Void) {
        if recoverable, response.isForMainFrame,
           let http = response.response as? HTTPURLResponse, http.statusCode >= 500,
           sameSite(http.url) {
            decisionHandler(.cancel)
            showOffline()
        } else if downstream?.webView?(webView, decidePolicyFor: response,
                                       decisionHandler: decisionHandler) == nil {
            decisionHandler(.allow)
        }
    }

    func webView(_ webView: WKWebView, didCommit navigation: WKNavigation!) {
        startupTimeout?.cancel()
        downstream?.webView?(webView, didCommit: navigation)
    }

    func webView(_ webView: WKWebView, didFinish navigation: WKNavigation!) {
        startupTimeout?.cancel()
        loadingBundle = false
        downstream?.webView?(webView, didFinish: navigation)
    }

    private func recover(_ error: Error) -> Bool {
        let failure = error as NSError
        let codes = [NSURLErrorNotConnectedToInternet, NSURLErrorTimedOut,
                     NSURLErrorCannotFindHost, NSURLErrorCannotConnectToHost,
                     NSURLErrorNetworkConnectionLost, NSURLErrorDNSLookupFailed]
        if recoverable && failure.domain == NSURLErrorDomain && codes.contains(failure.code) {
            showOffline()
            return true
        }
        // A cancellation from our own fallback must not cancel its navigation.
        if failure.code != NSURLErrorCancelled { startupTimeout?.cancel() }
        return false
    }

    func webView(_ webView: WKWebView, didFailProvisionalNavigation navigation: WKNavigation!,
                 withError error: Error) {
        if !recover(error) {
            downstream?.webView?(webView, didFailProvisionalNavigation: navigation, withError: error)
        }
    }

    func webView(_ webView: WKWebView, didFail navigation: WKNavigation!, withError error: Error) {
        if !recover(error) { downstream?.webView?(webView, didFail: navigation, withError: error) }
    }
}
