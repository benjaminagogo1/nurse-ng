package com.nurseng.app;

import android.os.Handler;
import android.os.Looper;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebView;
import android.webkit.SslErrorHandler;
import android.net.http.SslError;
import com.getcapacitor.Bridge;
import com.getcapacitor.BridgeWebViewClient;
import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.InputStream;
import java.net.URI;
import java.nio.charset.StandardCharsets;

/** Recover the existing origin's workspace without a service worker or cached HTML. */
final class OfflineWebViewClient extends BridgeWebViewClient {
    private final Bridge bridge;
    private final String origin;
    private final Handler handler = new Handler(Looper.getMainLooper());
    private final Runnable startupTimeout;
    private boolean loadingBundle;

    OfflineWebViewClient(Bridge bridge) {
        super(bridge);
        this.bridge = bridge;
        this.origin = bridge.getServerUrl();
        startupTimeout = () -> showOffline(bridge.getWebView());
        // Bound cold-start waiting, before there is a page on which to type.
        if (origin != null) handler.postDelayed(startupTimeout, 8000);
    }

    private boolean sameSite(String address) {
        if (origin == null || address == null) return false;
        try {
            URI expected = URI.create(origin);
            URI actual = URI.create(address);
            return expected.getScheme().equals(actual.getScheme())
                && expected.getRawAuthority().equals(actual.getRawAuthority());
        } catch (IllegalArgumentException error) {
            return false;
        }
    }

    private boolean recoverable(WebResourceRequest request) {
        return !loadingBundle && request.isForMainFrame()
            && "GET".equals(request.getMethod()) && sameSite(request.getUrl().toString());
    }

    private void showOffline(WebView view) {
        handler.removeCallbacks(startupTimeout);
        if (origin == null || loadingBundle) return;
        try (InputStream stream = bridge.getContext().getAssets().open("public/offline.html")) {
            ByteArrayOutputStream bytes = new ByteArrayOutputStream();
            byte[] buffer = new byte[8192];
            int count;
            while ((count = stream.read(buffer)) != -1) bytes.write(buffer, 0, count);
            loadingBundle = true;
            view.stopLoading();
            String base = origin.replaceAll("/+$", "") + "/offline-shell";
            // HTTPS baseURL preserves cookies, IndexedDB and Web Crypto for the
            // configured site. file:// or localhost would create a different store.
            view.loadDataWithBaseURL(base, bytes.toString(StandardCharsets.UTF_8.name()),
                "text/html", "UTF-8", base);
        } catch (IOException error) {
            // Build verification treats a missing bundle as a build failure.
            android.util.Log.e("NurseOffline", "Bundled workspace could not be read", error);
        }
    }

    @Override
    public void onPageCommitVisible(WebView view, String url) {
        handler.removeCallbacks(startupTimeout);
        super.onPageCommitVisible(view, url);
    }

    @Override
    public void onPageFinished(WebView view, String url) {
        handler.removeCallbacks(startupTimeout);
        loadingBundle = false;
        super.onPageFinished(view, url);
    }

    @Override
    public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
        int code = error.getErrorCode();
        // Do not hide certificate failures or replace a failed form submission.
        if (recoverable(request) && (code == ERROR_HOST_LOOKUP || code == ERROR_CONNECT
                || code == ERROR_IO || code == ERROR_TIMEOUT)) {
            showOffline(view);
            return;
        }
        if (request.isForMainFrame()) handler.removeCallbacks(startupTimeout);
        super.onReceivedError(view, request, error);
    }

    @Override
    public void onReceivedHttpError(WebView view, WebResourceRequest request,
            WebResourceResponse response) {
        if (recoverable(request) && response.getStatusCode() >= 500) {
            showOffline(view);
            return;
        }
        super.onReceivedHttpError(view, request, response);
    }

    @Override
    public void onReceivedSslError(WebView view, SslErrorHandler handler, SslError error) {
        this.handler.removeCallbacks(startupTimeout);
        super.onReceivedSslError(view, handler, error);
    }

    void dispose() {
        handler.removeCallbacks(startupTimeout);
    }
}
