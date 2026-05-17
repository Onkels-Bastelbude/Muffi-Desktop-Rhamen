const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

function askAdminPassword() {
  return new Promise((resolve) => {
    const modal = $('#admin-pw-modal');
    const input = $('#admin-pw-input');
    const ok = $('#admin-pw-ok');
    const cancel = $('#admin-pw-cancel');
    if (!modal || !input || !ok || !cancel) return resolve(null);

    const cleanup = () => {
      modal.classList.add('hidden');
      ok.onclick = null;
      cancel.onclick = null;
      input.value = '';
    };

    modal.classList.remove('hidden');
    setTimeout(() => input.focus(), 0);

    ok.onclick = () => {
      const v = input.value || '';
      cleanup();
      resolve(v || null);
    };
    cancel.onclick = () => {
      cleanup();
      resolve(null);
    };
  });
}

function setView(view) {
  $$('.nav-btn').forEach((b) => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach((v) => v.classList.toggle('active', v.dataset.view === view));
}

$('.mobile-toggle')?.addEventListener('click', () => $('#menu-list')?.classList.toggle('is-collapsed'));
$$('.nav-btn').forEach((btn) => btn.addEventListener('click', () => setView(btn.dataset.view)));

async function jget(url) { const r = await fetch(url); const d = await r.json(); if (!r.ok) throw new Error(d.error || 'Fehler'); return d; }
async function jpost(url, body) { const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body||{})}); const d = await r.json(); if (!r.ok) throw new Error(d.error || 'Fehler'); return d; }

let currentFrame = '';
let storageState = null;

function storageHealthLabel(s) {
  if (!s) return '-';
  if (s.writable) return 'erreichbar + schreibbar ✅';
  if (s.exists) return 'vorhanden, aber nicht schreibbar ⚠️';
  return 'nicht erreichbar ❌';
}

async function refreshServer() {
  try {
    const [status, cfg] = await Promise.all([jget('/api/status'), jget('/api/config')]);
    storageState = status.storage || null;
    $('#st-count').textContent = String(status.count ?? 0);
    $('#st-folder').textContent = status.photoDirExists ? 'ja' : 'nein';
    $('#st-mount').textContent = status.mountActive ? 'ja' : 'nein';
    $('#refresh-seconds').value = Math.max(10, Math.floor((cfg.refreshMs || 300000) / 1000));
    $('#conn-pill').textContent = 'Verbunden ✅';
    refreshStorageUi(storageState);
  } catch (e) {
    $('#conn-pill').textContent = 'Offline ❌';
  }
}

function refreshStorageUi(state) {
  if (!state) return;
  $('#storage-local-path').textContent = state.local?.path || '-';
  $('#storage-network-path').value = state.network?.path || '/mnt/muffi';
  $('#storage-local-status').textContent = storageHealthLabel(state.local);
  $('#storage-network-status').textContent = storageHealthLabel(state.network);
  $('#storage-local-card')?.classList.toggle('active', state.activeSource === 'local');
  $('#storage-network-card')?.classList.toggle('active', state.activeSource === 'network');
}

$('#storage-help-toggle')?.addEventListener('click', () => {
  $('#storage-help')?.classList.toggle('hidden');
});

function renderMedia(files) {
  const grid = $('#media-grid');
  if (!grid) return;
  grid.innerHTML = '';
  (files || []).slice().reverse().forEach((f) => {
    const el = document.createElement('div');
    el.className = 'media-item';
    el.innerHTML = `<img src="/${encodeURIComponent(f.name)}" alt="${f.name}"><div class="n">${f.name}</div><div class="row"><button data-del="${f.name}">Löschen</button></div>`;
    grid.appendChild(el);
  });
  grid.querySelectorAll('button[data-del]').forEach((b) => b.addEventListener('click', async () => {
    const name = b.getAttribute('data-del');
    if (!name || !confirm('Löschen?\n' + name)) return;
    try { await jpost('/api/delete', { name }); await refreshMediaAndFrame(); } catch (e) { alert(e.message); }
  }));
}

async function refreshMediaAndFrame() {
  try {
    const [list, fs] = await Promise.all([jget('/api/list'), jget('/api/frame-state')]);
    renderMedia(list.files || []);
    currentFrame = fs.filename || '';
    const has = !!fs.filename;
    $('#frame-empty')?.classList.toggle('hidden', has);
    $('#frame-image')?.classList.toggle('hidden', !has);
    if (has) {
      $('#frame-image').src = `/${encodeURIComponent(fs.filename)}?t=${Date.now()}`;
      $('#frame-name').textContent = fs.filename;
      const idx = Number(fs.index ?? -1), cnt = Number(fs.count ?? 0);
      $('#frame-meta').textContent = `${fs.orientation || '?'} · Pos ${idx >= 0 && cnt > 0 ? `${idx + 1}/${cnt}` : '-'}`;
    } else {
      $('#frame-name').textContent = '-';
      $('#frame-meta').textContent = '-';
    }
  } catch (_) {}
}

$('#delete-current-btn')?.addEventListener('click', async () => {
  if (!currentFrame) return;
  if (!confirm('Aktuelles Bild löschen?\n' + currentFrame)) return;
  try { await jpost('/api/delete', { name: currentFrame }); $('#frame-msg').textContent = '✅ gelöscht'; await refreshMediaAndFrame(); }
  catch (e) { $('#frame-msg').textContent = '❌ ' + e.message; }
});

$('#cfg-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    const sec = Number($('#refresh-seconds').value || 300);
    await jpost('/api/config', { refreshMs: sec * 1000 });
    $('#cfg-msg').textContent = '✅ gespeichert';
  } catch (e2) { $('#cfg-msg').textContent = '❌ ' + e2.message; }
});

let ledTimer = null;
async function ledSave(patch){ try { const d = await jpost('/api/led', { ...patch, source:'web' }); $('#led-on').checked = !!d.on; $('#led-brightness').value = Number(d.brightness||0); $('#led-brightness-val').textContent = String(Number(d.brightness||0)); $('#led-color').value = d.color || '#FFD6A0'; $('#led-order').value = d.ledOrder || 'GRB'; $('#led-msg').textContent='✅ gespeichert'; } catch(e){ $('#led-msg').textContent='❌ '+e.message; } }
function queueLed(p){ clearTimeout(ledTimer); ledTimer = setTimeout(()=>ledSave(p), 120); }

$('#led-on')?.addEventListener('change', ()=>ledSave({ on: $('#led-on').checked }));
$('#led-brightness')?.addEventListener('input', ()=>{ const v=Number($('#led-brightness').value||0); $('#led-brightness-val').textContent=String(v); queueLed({ brightness:v }); });
$('#led-color')?.addEventListener('input', ()=>queueLed({ color: $('#led-color').value, colorIndex:-1 }));
$('#led-order')?.addEventListener('change', ()=>ledSave({ ledOrder: $('#led-order').value }));
$('#led-next-color')?.addEventListener('click', async ()=>{ try { const d = await jget('/api/led'); const c = Array.isArray(d.catalog)?d.catalog:[]; const n = c.length ? ((Number(d.colorIndex ?? -1)+1)%c.length) : -1; if(n>=0) ledSave({ color:c[n].hex, colorIndex:n, on:true }); } catch(e){} });

async function ledRefresh(){ try { const d = await jget('/api/led'); $('#led-on').checked=!!d.on; $('#led-brightness').value=Number(d.brightness||0); $('#led-brightness-val').textContent=String(Number(d.brightness||0)); $('#led-color').value=d.color||'#FFD6A0'; $('#led-order').value=d.ledOrder||'GRB'; } catch(_){} }

async function wlanRefresh(){
  try {
    const d = await jget('/api/wlan');
    $('#wlan-ssid').value = d.ssid || '';
    $('#wlan-password').value = d.password || '';
    $('#wlan-esp-host').value = d.espHost || '';
    $('#wlan-server-base').value = d.serverBase || 'http://frame-server.local:8765';
  } catch (_) {}
}

$('#wlan-form')?.addEventListener('submit', async (e) => {
  e.preventDefault();
  try {
    await jpost('/api/wlan', {
      ssid: $('#wlan-ssid').value,
      password: $('#wlan-password').value,
      espHost: $('#wlan-esp-host').value,
      serverBase: $('#wlan-server-base').value,
    });
    $('#wlan-msg').textContent = '✅ WLAN-Konfig gespeichert';
  } catch (e2) {
    $('#wlan-msg').textContent = '❌ ' + e2.message;
  }
});

$('#wlan-test-btn')?.addEventListener('click', async () => {
  try {
    $('#wlan-msg').textContent = 'Teste ESP…';
    const d = await jpost('/api/wlan/test', { espHost: $('#wlan-esp-host').value });
    $('#wlan-msg').textContent = '✅ ' + (d.message || 'ESP erreichbar');
  } catch (e2) {
    $('#wlan-msg').textContent = '❌ ' + e2.message;
  }
});

$('#use-local-btn')?.addEventListener('click', async () => {
  try {
    const d = await jpost('/api/storage', { mode: 'local' });
    storageState = d;
    refreshStorageUi(storageState);
    $('#storage-msg').textContent = '✅ Lokaler Ordner ist jetzt aktiv.';
    await refreshMediaAndFrame();
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
  }
});

$('#use-network-btn')?.addEventListener('click', async () => {
  try {
    const raw = ($('#storage-network-path')?.value || '/mnt/muffi').trim();
    const d = await jpost('/api/storage', { mode: 'network', networkPath: raw });
    storageState = d;
    refreshStorageUi(storageState);
    const ok = d.activeSource === 'network';
    const converted = !!d.normalizedNetworkPathFrom;
    const path = d.network?.path || '/mnt/muffi';
    const hint = d.normalizedNetworkPathHint ? ` ${d.normalizedNetworkPathHint}` : '';
    if (d.shareSwitchRequired || d.blocked) {
      $('#storage-msg').textContent = `⚠️ Share-Wechsel erkannt. Bitte "Share wechseln (Admin)" nutzen.${hint}`;
    } else {
      $('#storage-msg').textContent = ok
        ? `✅ Netzwerkordner ist jetzt aktiv.${converted ? ` (UNC → ${path})` : ''}${hint}`
        : `⚠️ Netzwerkordner nicht nutzbar, lokal bleibt aktiv.${converted ? ` (UNC → ${path})` : ''}${hint}`;
    }
    await refreshMediaAndFrame();
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
  }
});

$('#save-network-path-btn')?.addEventListener('click', async () => {
  try {
    const raw = ($('#storage-network-path')?.value || '/mnt/muffi').trim();
    const d = await jpost('/api/storage', { mode: 'auto', networkPath: raw });
    storageState = d;
    refreshStorageUi(storageState);
    const path = d.network?.path || '/mnt/muffi';
    const hint = d.normalizedNetworkPathHint ? ` ${d.normalizedNetworkPathHint}` : '';
    if (d.shareSwitchRequired || d.blocked) {
      $('#storage-msg').textContent = `⚠️ Das ist ein anderer Share. Pfad nicht übernommen. Bitte "Share wechseln (Admin)" nutzen.${hint}`;
    } else {
      $('#storage-msg').textContent = `✅ Netzwerkpfad gespeichert.${d.normalizedNetworkPathFrom ? ` (UNC → ${path})` : ''}${hint}`;
    }
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
  }
});

$('#share-switch-check-btn')?.addEventListener('click', async () => {
  try {
    const raw = ($('#storage-network-path')?.value || '').trim();
    if (!raw) {
      $('#storage-msg').textContent = 'ℹ️ Bitte zuerst einen UNC-Pfad einfügen.';
      return;
    }
    const d = await jpost('/api/storage/share-check', { networkPath: raw });
    if (!(d.shareSwitchRequired || d.blocked)) {
      $('#storage-msg').textContent = `✅ Kein Share-Wechsel nötig. Du kannst direkt "Ordner speichern"/"Netzwerkordner nutzen" verwenden.${d.mappedPath ? ` Ziel: ${d.mappedPath}` : ''}`;
      return;
    }

    const pw = await askAdminPassword();
    if (!pw) {
      $('#storage-msg').textContent = 'ℹ️ Abgebrochen.';
      return;
    }

    const r = await jpost('/api/storage/share-switch', { password: pw, networkPath: raw });
    storageState = r;
    refreshStorageUi(storageState);
    $('#storage-msg').textContent = `✅ ${r.message || 'Share gewechselt'} – Netzwerkordner aktiv.`;
    await refreshMediaAndFrame();
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
  }
});

$('#fw-ota-btn')?.addEventListener('click', async () => {
  try {
    $('#fw-msg').textContent = 'Prüfe OTA-Erreichbarkeit…';
    const host = ($('#wlan-esp-host')?.value || '').trim();
    const d = await jpost('/api/wlan/test', { espHost: host });
    $('#fw-msg').textContent = `✅ ${d.message || 'ESP erreichbar'} · Nächster Schritt: OTA Upload aus der IDE/CLI starten.`;
  } catch (e2) {
    $('#fw-msg').textContent = '❌ OTA aktuell nicht erreichbar: ' + e2.message;
  }
});

$('#fw-usb-btn')?.addEventListener('click', () => {
  $('#fw-msg').textContent = 'ℹ️ USB-Flash: ESP per Datenkabel verbinden, BOOT halten + RESET tippen, dann Upload starten.';
});

$('#upload-form')?.addEventListener('submit', (e) => {
  e.preventDefault();
  const file = $('#upload-file').files?.[0];
  if (!file) return;
  $('#upload-progress').value = 0;
  $('#upload-msg').textContent = 'Upload…';
  const xhr = new XMLHttpRequest();
  xhr.open('POST', '/api/upload?name=' + encodeURIComponent(file.name));
  xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream');
  xhr.upload.onprogress = (ev) => { if (ev.lengthComputable) $('#upload-progress').value = Math.round((ev.loaded / ev.total) * 100); };
  xhr.onload = async () => {
    try { const d = JSON.parse(xhr.responseText || '{}'); if (xhr.status >= 200 && xhr.status < 300) { $('#upload-msg').textContent = '✅ ' + (d.filename || file.name); await refreshMediaAndFrame(); } else throw new Error(d.error || 'Upload fehlgeschlagen'); }
    catch (err) { $('#upload-msg').textContent = '❌ ' + err.message; }
  };
  xhr.onerror = () => $('#upload-msg').textContent = '❌ Netzwerkfehler';
  xhr.send(file);
});

(async function init(){ await refreshServer(); await ledRefresh(); await wlanRefresh(); await refreshMediaAndFrame(); setInterval(refreshMediaAndFrame, 3500); setInterval(ledRefresh, 2500); setInterval(refreshServer, 10000); })();
