#!/usr/bin/env bash
# Prepara la versione web per Netlify: copia l'app, aggiunge proxy, manifest e icone per la schermata Home.
set -e
rm -rf dist && mkdir -p dist
cp -R Scommetti/Web/. dist/
cp Scommetti/Assets.xcassets/AppIcon.appiconset/icon.png dist/icon-1024.png
cp Scommetti/Web/icons/default.png dist/apple-touch-icon.png
python3 - <<'PY'
from pathlib import Path
p=Path('dist/index.html');s=p.read_text()
head='''<meta name="scommetti-proxy" content="/api">
<meta name="theme-color" content="#0B1220">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="black-translucent">
<meta name="apple-mobile-web-app-title" content="Scommetti">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
<link rel="icon" href="apple-touch-icon.png">
'''
s=s.replace('<title>Scommetti Pronostici</title>','<title>Scommetti Pronostici</title>\n'+head,1)
s=s.replace('</body>','<script>if("serviceWorker" in navigator)navigator.serviceWorker.register("sw.js").catch(()=>{})</script>\n</body>',1)
p.write_text(s)
Path('dist/manifest.webmanifest').write_text('''{"name":"Scommetti Pronostici","short_name":"Scommetti","lang":"it","start_url":"./","scope":"./","display":"standalone","orientation":"portrait",
"background_color":"#0B1220","theme_color":"#0B1220",
"icons":[{"src":"apple-touch-icon.png","sizes":"180x180","type":"image/png"},{"src":"icon-1024.png","sizes":"1024x1024","type":"image/png","purpose":"any"}]}''')
Path('dist/sw.js').write_text('''const C="scommetti-v1";
self.addEventListener("install",e=>{self.skipWaiting();e.waitUntil(caches.open(C).then(c=>c.addAll(["./","index.html","manifest.webmanifest","apple-touch-icon.png"])))});
self.addEventListener("activate",e=>e.waitUntil(self.clients.claim()));
self.addEventListener("fetch",e=>{const u=new URL(e.request.url);if(e.request.method!=="GET"||u.origin!==location.origin||u.pathname.startsWith("/api/"))return;
  e.respondWith(fetch(e.request).then(r=>{const c=r.clone();caches.open(C).then(x=>x.put(e.request,c));return r}).catch(()=>caches.match(e.request)))});''')
PY
echo "Versione web pronta in dist/"
