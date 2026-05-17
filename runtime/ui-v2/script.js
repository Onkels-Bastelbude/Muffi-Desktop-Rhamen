const $ = (s) => document.querySelector(s);
const $$ = (s) => Array.from(document.querySelectorAll(s));

let adminPasswordCache = '';
try { adminPasswordCache = sessionStorage.getItem('muffiAdminPw') || ''; } catch (_) {}

function clearAdminPasswordCache() {
  adminPasswordCache = '';
  try {
    sessionStorage.removeItem('muffiAdminPw');
    sessionStorage.removeItem('muffiAdminPwRemember');
  } catch (_) {}
}

function askAdminPassword(opts = {}) {
  const forcePrompt = !!opts.forcePrompt;
  if (!forcePrompt && adminPasswordCache) {
    return Promise.resolve(adminPasswordCache);
  }

  return new Promise((resolve) => {
    const modal = $('#admin-pw-modal');
    const input = $('#admin-pw-input');
    const remember = $('#admin-pw-remember');
    const ok = $('#admin-pw-ok');
    const cancel = $('#admin-pw-cancel');
    if (!modal || !input || !ok || !cancel) return resolve(null);

    const cleanup = () => {
      modal.classList.add('hidden');
      ok.onclick = null;
      cancel.onclick = null;
      input.value = '';
      if (remember) remember.checked = false;
    };

    modal.classList.remove('hidden');
    setTimeout(() => input.focus(), 0);

    ok.onclick = () => {
      const v = input.value || '';
      const keep = !!remember?.checked;
      if (v && keep) {
        adminPasswordCache = v;
        try {
          sessionStorage.setItem('muffiAdminPw', v);
          sessionStorage.setItem('muffiAdminPwRemember', '1');
        } catch (_) {}
      } else {
        clearAdminPasswordCache();
      }
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
let storageAutoBusy = false;

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
  const networkInput = $('#storage-network-path');
  if (networkInput && document.activeElement !== networkInput) {
    networkInput.value = state.network?.path || '/mnt/muffi';
  }
  $('#storage-local-status').textContent = storageHealthLabel(state.local);
  $('#storage-network-status').textContent = storageHealthLabel(state.network);
  $('#storage-local-card')?.classList.toggle('active', state.activeSource === 'local');
  $('#storage-network-card')?.classList.toggle('active', state.activeSource === 'network');
}

function renderStorageDiagnostics(d) {
  const el = $('#storage-diagnose-log');
  if (!el || !d) return;
  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, (ch) => ({ '&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;' }[ch]));
  const checks = Array.isArray(d.checklist) ? d.checklist : [];
  const badge = $('#diag70-status-badge');
  if (badge) {
    badge.className = 'diag70-badge ' + (d.ok ? 'diag70-ok' : 'diag70-warn');
    badge.textContent = d.ok ? 'OK ✅' : 'PROBLEM ⚠️';
  }
  $('#diag70-reason').textContent = d.reason || '-';
  $('#diag70-next').textContent = d.nextAction || '-';

  const checksEl = $('#diag70-checks');
  if (checksEl) {
    checksEl.innerHTML = checks.map((c) => `
      <div class="diag70-check">
        <span class="diag70-check-label">${esc(c.label || c.key || '-')}</span>
        <span class="diag70-check-val">${c.ok ? '✅ OK' : '❌ FEHLT'}</span>
      </div>
    `).join('');
  }

  const chipsEl = $('#diag70-chips');
  if (chipsEl) {
    chipsEl.innerHTML = [
      `Quelle: ${esc(d.activeSource || '-')}`,
      `Pfad: ${esc(d.networkPath || '-')}`,
      `Mount: ${esc(d.mountInfo || '-')}`,
      `Owner/Mode: ${esc(d.pathOwner || '-')} / ${esc(d.pathMode || '-')}`,
    ].map((x) => `<span class="diag70-chip">${x}</span>`).join('');
  }
}

async function refreshStorageDiagnostics() {
  try {
    const d = await jget('/api/storage/diagnostics');
    renderStorageDiagnostics(d);
    return d;
  } catch (e) {
    const badge = $('#diag70-status-badge');
    if (badge) {
      badge.className = 'diag70-badge diag70-err';
      badge.textContent = 'OFFLINE ❌';
    }
    const reason = $('#diag70-reason');
    if (reason) reason.textContent = 'Diagnose fehlgeschlagen: ' + (e?.message || e);
    const next = $('#diag70-next');
    if (next) next.textContent = 'Server prüfen und erneut versuchen.';
    return null;
  }
}

function setStorageAutoMsg(text) {
  const el = $('#storage-auto-msg');
  if (el) el.textContent = text || '';
}

function isCheckOk(diag, key) {
  const arr = Array.isArray(diag?.checklist) ? diag.checklist : [];
  const item = arr.find((x) => x?.key === key);
  return !!item?.ok;
}

async function runStorageAutoConnect() {
  if (storageAutoBusy) return;
  storageAutoBusy = true;
  const autoBtn = $('#storage-auto-fix-btn');
  if (autoBtn) autoBtn.disabled = true;

  try {
    const raw = ($('#storage-network-path')?.value || '').trim();
    if (!raw) throw new Error('Bitte zuerst einen Netzwerkpfad eintragen.');

    setStorageAutoMsg('🔎 Prüfe Eingabe und aktuellen Status …');
    const share = await jpost('/api/storage/share-check', { networkPath: raw });

    let adminPw = null;
    if (share.shareSwitchRequired || share.blocked) {
      setStorageAutoMsg('🔐 Share muss umgestellt werden. Bitte Passwort eingeben …');
      adminPw = await askAdminPassword();
      if (!adminPw) throw new Error('Abgebrochen (kein Passwort eingegeben).');
      await jpost('/api/storage/share-switch', { password: adminPw, networkPath: raw });
    } else {
      await jpost('/api/storage', { mode: 'auto', networkPath: raw });
    }

    setStorageAutoMsg('🔌 Verbinde Share neu …');
    if (!adminPw) {
      adminPw = await askAdminPassword();
      if (!adminPw) throw new Error('Abgebrochen (kein Passwort eingegeben).');
    }
    await jpost('/api/storage/remount', { password: adminPw });

    setStorageAutoMsg('✅ Prüfe Verbindung und aktiviere Netzwerkordner …');
    const diag = await refreshStorageDiagnostics();
    if (!diag?.ok && (!isCheckOk(diag, 'is_mount') || !isCheckOk(diag, 'writable'))) {
      throw new Error(`${diag?.reason || 'Share nicht bereit.'} ${diag?.nextAction || ''}`.trim());
    }

    const d = await jpost('/api/storage', { mode: 'network', networkPath: raw });
    storageState = d;
    refreshStorageUi(storageState);
    await refreshServer();
    await refreshMediaAndFrame();
    const finalDiag = await refreshStorageDiagnostics();

    if (d.activeSource === 'network') {
      setStorageAutoMsg('🎉 Fertig! Netzwerkordner ist jetzt aktiv.');
      $('#storage-msg').textContent = '✅ Automatisch verbunden. Medien laufen jetzt über den Netzwerkordner.';
    } else {
      throw new Error(finalDiag?.reason || 'Umschalten auf Netzwerk ist fehlgeschlagen.');
    }
  } catch (e) {
    const msg = e?.message || String(e);
    setStorageAutoMsg(`⚠️ Hat nicht geklappt: ${msg}`);
    $('#storage-msg').textContent = `⚠️ Automatik konnte nicht abschließen: ${msg}`;
    await refreshStorageDiagnostics();
  } finally {
    storageAutoBusy = false;
    if (autoBtn) autoBtn.disabled = false;
  }
}

$('#storage-help-toggle')?.addEventListener('click', () => {
  $('#storage-help')?.classList.toggle('hidden');
});

$('#admin-pw-clear-btn')?.addEventListener('click', () => {
  clearAdminPasswordCache();
  $('#storage-msg').textContent = '✅ Gespeichertes Admin-Passwort wurde gelöscht.';
});

function storageCardClickIsInteractive(target) {
  return !!target?.closest('button,input,select,textarea,a,label,code,pre');
}

$('#storage-local-card')?.addEventListener('click', (e) => {
  if (storageCardClickIsInteractive(e.target)) return;
  $('#use-local-btn')?.click();
});

$('#storage-network-card')?.addEventListener('click', async (e) => {
  if (storageCardClickIsInteractive(e.target)) return;
  $('#use-network-btn')?.click();
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
    const pre = await refreshStorageDiagnostics();
    if (pre && !pre.ok) {
      $('#storage-msg').textContent = `⚠️ Aktivierung blockiert: ${pre.reason} ${pre.nextAction || ''}`.trim();
      return;
    }

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
    if (!ok) {
      const diag = await refreshStorageDiagnostics();
      if (diag?.reason) {
        $('#storage-msg').textContent += ` Grund: ${diag.reason}`;
      }
    }
    await refreshMediaAndFrame();
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
  }
});

$('#remount-network-btn')?.addEventListener('click', async () => {
  try {
    const pw = await askAdminPassword();
    if (!pw) {
      $('#storage-msg').textContent = 'ℹ️ Abgebrochen.';
      return;
    }
    const r = await jpost('/api/storage/remount', { password: pw });
    await refreshServer();
    const diag = await refreshStorageDiagnostics();
    $('#storage-msg').textContent = `✅ ${r.message || 'Share neu verbunden'}` + (diag?.reason ? ` · ${diag.reason}` : '');
  } catch (e2) {
    $('#storage-msg').textContent = '❌ ' + e2.message;
    await refreshStorageDiagnostics();
  }
});

$('#storage-diagnose-btn')?.addEventListener('click', async () => {
  const d = await refreshStorageDiagnostics();
  if (d?.reason) {
    $('#storage-msg').textContent = `ℹ️ Diagnose: ${d.reason}`;
  }
});

$('#save-network-path-btn')?.addEventListener('click', async () => {
  await runStorageAutoConnect();
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
      $('#storage-msg').textContent = `✅ Share-Wechsel nicht nötig. Nutze jetzt Schritt 2 oder 3.${d.mappedPath ? ` Ziel: ${d.mappedPath}` : ''}`;
      await refreshStorageDiagnostics();
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
    const diag = await refreshStorageDiagnostics();
    $('#storage-msg').textContent = `✅ ${r.message || 'Share gewechselt'}${diag?.reason ? ` · ${diag.reason}` : ''}`;
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

(async function init(){ await refreshServer(); const d = await refreshStorageDiagnostics(); setStorageAutoMsg(d?.ok ? '✅ Verbindung ist bereit. Du kannst direkt automatisch verbinden.' : 'Assistent bereit. Pfad eintragen und auf „Automatisch verbinden“ klicken.'); await ledRefresh(); await wlanRefresh(); await refreshMediaAndFrame(); setInterval(refreshMediaAndFrame, 3500); setInterval(ledRefresh, 2500); setInterval(refreshServer, 10000); })();
