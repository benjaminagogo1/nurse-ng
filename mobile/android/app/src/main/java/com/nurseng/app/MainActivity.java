package com.nurseng.app;

import android.os.Bundle;
import androidx.activity.OnBackPressedCallback;
import com.getcapacitor.BridgeActivity;

public class MainActivity extends BridgeActivity {
    private OfflineWebViewClient offlineClient;

    @Override
    public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        if (getBridge() == null) return;
        offlineClient = new OfflineWebViewClient(getBridge());
        getBridge().setWebViewClient(offlineClient);
        getOnBackPressedDispatcher().addCallback(this, new OnBackPressedCallback(true) {
            @Override
            public void handleOnBackPressed() {
                if (getBridge().getWebView().canGoBack()) {
                    getBridge().getWebView().goBack();
                } else {
                    moveTaskToBack(true);
                }
            }
        });
    }

    @Override
    public void onResume() {
        super.onResume();
        if (getBridge() != null) {
            getBridge().eval("document.dispatchEvent(new Event('nurse:sync-request'))", null);
        }
    }

    @Override
    public void onDestroy() {
        if (offlineClient != null) offlineClient.dispose();
        super.onDestroy();
    }
}
