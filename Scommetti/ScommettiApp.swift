import SwiftUI
import WebKit

@main
struct ScommettiApp: App {
    var body: some Scene {
        WindowGroup {
            AppWebView()
                .ignoresSafeArea()
        }
    }
}

/// Mostra l'app web inclusa nel pacchetto e le fornisce un ponte di rete nativo,
/// così le richieste a risultati e quote non sono bloccate dalle regole CORS del browser.
struct AppWebView: UIViewRepresentable {
    func makeCoordinator() -> Coordinator { Coordinator() }

    func makeUIView(context: Context) -> WKWebView {
        let config = WKWebViewConfiguration()
        config.websiteDataStore = .default()
        config.userContentController.addScriptMessageHandler(context.coordinator, contentWorld: .page, name: "net")

        let webView = WKWebView(frame: .zero, configuration: config)
        webView.navigationDelegate = context.coordinator
        webView.uiDelegate = context.coordinator
        webView.isOpaque = false
        webView.backgroundColor = .systemBackground
        webView.scrollView.contentInsetAdjustmentBehavior = .never
        webView.allowsBackForwardNavigationGestures = false

        if let url = Bundle.main.url(forResource: "index", withExtension: "html", subdirectory: "Web") {
            webView.loadFileURL(url, allowingReadAccessTo: url.deletingLastPathComponent())
        }
        return webView
    }

    func updateUIView(_ uiView: WKWebView, context: Context) {}

    final class Coordinator: NSObject, WKScriptMessageHandlerWithReply, WKNavigationDelegate, WKUIDelegate {
        private let allowedHosts: Set<String> = [
            "raw.githubusercontent.com",
            "api.football-data.org",
            "api.the-odds-api.com"
        ]

        func userContentController(_ userContentController: WKUserContentController,
                                   didReceive message: WKScriptMessage,
                                   replyHandler: @escaping (Any?, String?) -> Void) {
            guard let body = message.body as? [String: Any],
                  let text = body["url"] as? String,
                  let url = URL(string: text),
                  url.scheme == "https",
                  let host = url.host, allowedHosts.contains(host) else {
                replyHandler(nil, "Indirizzo non consentito")
                return
            }
            var request = URLRequest(url: url, timeoutInterval: 25)
            if let headers = body["headers"] as? [String: String] {
                for (key, value) in headers { request.setValue(value, forHTTPHeaderField: key) }
            }
            URLSession.shared.dataTask(with: request) { data, response, error in
                DispatchQueue.main.async {
                    if let error = error {
                        replyHandler(nil, error.localizedDescription)
                        return
                    }
                    let status = (response as? HTTPURLResponse)?.statusCode ?? 0
                    let text = data.flatMap { String(data: $0, encoding: .utf8) } ?? ""
                    replyHandler(["status": status, "body": text], nil)
                }
            }.resume()
        }

        // I link esterni (registrazione chiavi, siti dei bookmaker) si aprono in Safari.
        func webView(_ webView: WKWebView,
                     decidePolicyFor navigationAction: WKNavigationAction,
                     decisionHandler: @escaping (WKNavigationActionPolicy) -> Void) {
            if let url = navigationAction.request.url, url.scheme == "https" || url.scheme == "http" {
                UIApplication.shared.open(url)
                decisionHandler(.cancel)
                return
            }
            decisionHandler(.allow)
        }

        func webView(_ webView: WKWebView,
                     createWebViewWith configuration: WKWebViewConfiguration,
                     for navigationAction: WKNavigationAction,
                     windowFeatures: WKWindowFeatures) -> WKWebView? {
            if let url = navigationAction.request.url { UIApplication.shared.open(url) }
            return nil
        }
    }
}
