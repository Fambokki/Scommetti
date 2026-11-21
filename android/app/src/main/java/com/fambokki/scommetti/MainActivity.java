package com.fambokki.scommetti;

import android.app.Activity;
import android.content.ComponentName;
import android.content.Intent;
import android.content.pm.PackageManager;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.os.Handler;
import android.os.Looper;
import android.webkit.JavascriptInterface;
import android.webkit.WebResourceRequest;
import android.webkit.WebResourceResponse;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;

import androidx.webkit.WebViewAssetLoader;

import org.json.JSONObject;

import java.io.ByteArrayOutputStream;
import java.io.InputStream;
import java.net.HttpURLConnection;
import java.net.URL;
import java.util.Arrays;
import java.util.HashSet;
import java.util.Iterator;
import java.util.Set;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Mostra l'app web inclusa nel pacchetto (assets/web) e le offre lo stesso ponte nativo dell'app iOS:
 * "net" scarica risultati e quote senza i blocchi del browser, "icon" cambia l'icona sulla schermata Home.
 */
public class MainActivity extends Activity {
    private static final String HOST = "appassets.androidplatform.net";
    private static final Set<String> ALLOWED = new HashSet<>(Arrays.asList(
            "raw.githubusercontent.com", "api.football-data.org", "api.the-odds-api.com"));
    private static final String[][] ICONS = {
            {"default", ".IconDefault"}, {"AppIcon-Campo", ".IconCampo"}, {"AppIcon-Schedina", ".IconSchedina"},
            {"AppIcon-Notte", ".IconNotte"}, {"AppIcon-Oro", ".IconOro"}};

    private WebView web;
    private final ExecutorService pool = Executors.newFixedThreadPool(4);
    private final Handler main = new Handler(Looper.getMainLooper());

    @Override
    protected void onCreate(Bundle state) {
        super.onCreate(state);
        web = new WebView(this);
        web.setBackgroundColor(Color.parseColor("#0B1220"));
        web.setOverScrollMode(WebView.OVER_SCROLL_NEVER);
        WebSettings s = web.getSettings();
        s.setJavaScriptEnabled(true);
        s.setDomStorageEnabled(true);
        s.setTextZoom(100);

        final WebViewAssetLoader loader = new WebViewAssetLoader.Builder()
                .addPathHandler("/assets/", new WebViewAssetLoader.AssetsPathHandler(this))
                .build();
        web.setWebViewClient(new WebViewClient() {
            @Override
            public WebResourceResponse shouldInterceptRequest(WebView view, WebResourceRequest req) {
                return loader.shouldInterceptRequest(req.getUrl());
            }

            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest req) {
                Uri u = req.getUrl();
                if (HOST.equals(u.getHost())) return false;
                try { startActivity(new Intent(Intent.ACTION_VIEW, u)); } catch (Exception ignored) {}
                return true;
            }
        });
        web.addJavascriptInterface(new Bridge(), "AndroidNet");
        setContentView(web);
        if (state != null) web.restoreState(state);
        else web.loadUrl("https://" + HOST + "/assets/web/index.html");
    }

    @Override
    protected void onSaveInstanceState(Bundle out) {
        super.onSaveInstanceState(out);
        web.saveState(out);
    }

    private void reply(int id, boolean ok, String payload) {
        final String js = "window.__androidCb&&window.__androidCb(" + id + "," + ok + "," + JSONObject.quote(payload) + ")";
        main.post(() -> web.evaluateJavascript(js, null));
    }

    private class Bridge {
        @JavascriptInterface
        public void post(String name, int id, String json) {
            if ("icon".equals(name)) { main.post(() -> handleIcon(id, json)); return; }
            pool.execute(() -> handleNet(id, json));
        }
    }

    private void handleNet(int id, String json) {
        try {
            JSONObject o = new JSONObject(json);
            URL url = new URL(o.getString("url"));
            if (!"https".equals(url.getProtocol()) || !ALLOWED.contains(url.getHost())) {
                reply(id, false, "Indirizzo non consentito");
                return;
            }
            HttpURLConnection c = (HttpURLConnection) url.openConnection();
            c.setConnectTimeout(20000);
            c.setReadTimeout(25000);
            JSONObject h = o.optJSONObject("headers");
            if (h != null) for (Iterator<String> it = h.keys(); it.hasNext(); ) { String k = it.next(); c.setRequestProperty(k, h.getString(k)); }
            int status = c.getResponseCode();
            InputStream in = status >= 400 ? c.getErrorStream() : c.getInputStream();
            String body = "";
            if (in != null) {
                ByteArrayOutputStream b = new ByteArrayOutputStream();
                byte[] buf = new byte[16384];
                int n;
                while ((n = in.read(buf)) > 0) b.write(buf, 0, n);
                in.close();
                body = b.toString("UTF-8");
            }
            c.disconnect();
            JSONObject r = new JSONObject();
            r.put("status", status);
            r.put("body", body);
            reply(id, true, r.toString());
        } catch (Exception e) {
            reply(id, false, "Connessione non riuscita");
        }
    }

    private void handleIcon(int id, String json) {
        PackageManager pm = getPackageManager();
        String current = "default";
        for (String[] ic : ICONS) {
            int st = pm.getComponentEnabledSetting(new ComponentName(this, getPackageName() + ic[1]));
            boolean on = st == PackageManager.COMPONENT_ENABLED_STATE_ENABLED
                    || (st == PackageManager.COMPONENT_ENABLED_STATE_DEFAULT && ic[0].equals("default"));
            if (on) current = ic[0];
        }
        try {
            JSONObject o = new JSONObject(json);
            String target = o.optString("set", "");
            if (target.isEmpty() || target.equals(current)) { reply(id, true, JSONObject.quote(current)); return; }
            String alias = null;
            for (String[] ic : ICONS) if (ic[0].equals(target)) alias = ic[1];
            if (alias == null) { reply(id, false, "Icona sconosciuta"); return; }
            pm.setComponentEnabledSetting(new ComponentName(this, getPackageName() + alias),
                    PackageManager.COMPONENT_ENABLED_STATE_ENABLED, PackageManager.DONT_KILL_APP);
            for (String[] ic : ICONS) if (!ic[1].equals(alias))
                pm.setComponentEnabledSetting(new ComponentName(this, getPackageName() + ic[1]),
                        PackageManager.COMPONENT_ENABLED_STATE_DISABLED, PackageManager.DONT_KILL_APP);
            reply(id, true, JSONObject.quote(target));
        } catch (Exception e) {
            reply(id, false, "Non è stato possibile cambiare icona");
        }
    }
}
