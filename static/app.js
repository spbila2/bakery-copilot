// עוזר הכספים של המועצה: שכבת הממשק. היא מציגה מה שהשרת שולח, ולא זוכרת דבר בעצמה.
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { user: null, conversations: [], current: null, image: null, streaming: false };
  const BOT_NAME = "עוזר הכספים";
  const TOOL_LABELS = { budget_query: "שאילתת תקציב", lookup_supplier: "חיפוש ספק", log_invoice: "רישום חשבונית" };
  const STATUS_LABELS = { logged: "נרשמה", needs_a_look: "דורשת בדיקה" };
  const REASON_LABELS = {
    outside_range: "מחוץ לטווח הרגיל של הספק", over_budget: "חריגה מהתקציב השנתי", unknown_supplier: "ספק לא מוכר",
    ambiguous_supplier: "שם ספק דו-משמעי", amount_unreadable: "סכום לא קריא",
  };
  const HINTS = ["מה התקציב לכל פרק?", "כמה נשאר בתקציב החשמל של המקוואות?", "על איזו קטגוריה הוצאנו הכי הרבה?", "כמה שילמנו לכל ספק בחודש מרץ?"];

  // ---------- helpers ----------
  async function api(path, options = {}) {
    const res = await fetch(path, { headers: { "Content-Type": "application/json" }, credentials: "same-origin", ...options });
    if (res.status === 401) { showLogin(); throw new Error("יש להתחבר."); }
    if (!res.ok) {
      let detail = res.statusText;
      try { detail = (await res.json()).detail || detail; } catch (_) {}
      throw new Error(detail);
    }
    return res.status === 204 ? null : res.json();
  }
  function render(md) {
    if (window.marked) { try { return marked.parse(md, { breaks: true }); } catch (_) {} }
    const div = document.createElement("div"); div.textContent = md; return div.innerHTML.replace(/\n/g, "<br>");
  }
  function escapeHtml(s) { const d = document.createElement("div"); d.textContent = s == null ? "" : String(s); return d.innerHTML; }
  function fmtDate(iso) { const m = /^(\d{4})-(\d{2})-(\d{2})/.exec(iso || ""); return m ? `${m[3]}/${m[2]}/${m[1]}` : ""; }
  function setStatus(text) { $("status").textContent = text || ""; }
  function scrollDown() { const m = $("messages"); m.scrollTop = m.scrollHeight; }
  // While an answer streams in, keep its first line in view: a long answer must be read from the top,
  // not from the bottom. A short answer still follows to the bottom, so it stays next to the composer.
  function followAnswer(el) {
    const m = $("messages");
    const top = el.getBoundingClientRect().top - m.getBoundingClientRect().top + m.scrollTop - 12;
    if (el.offsetHeight + 24 > m.clientHeight) m.scrollTop = top; else scrollDown();
  }

  // ---------- auth ----------
  function showLogin() { $("login").classList.remove("hidden"); $("app").classList.add("hidden"); }
  function showApp() { $("login").classList.add("hidden"); $("app").classList.remove("hidden"); $("who").textContent = state.user ? `מחובר/ת: ${state.user.name}` : ""; }

  $("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    $("login-error").textContent = "";
    try {
      state.user = await api("/api/login", { method: "POST", body: JSON.stringify({ name: $("login-name").value.trim(), password: $("login-password").value }) });
      $("login-password").value = "";
      showApp();
      await loadConversations();
    } catch (err) { $("login-error").textContent = err.message; }
  });
  $("logout").addEventListener("click", async () => { await api("/api/logout", { method: "POST" }).catch(() => {}); state.user = null; state.current = null; showLogin(); });

  // ---------- conversations ----------
  async function loadConversations() {
    state.conversations = await api("/api/conversations");
    renderConversations();
    if (state.current) await openConversation(state.current); else renderEmpty();
  }
  function renderConversations() {
    const nav = $("conversations"); nav.innerHTML = "";
    for (const c of state.conversations) {
      const b = document.createElement("button");
      b.textContent = c.title; b.title = c.title;
      if (c.id === state.current) b.classList.add("active");
      b.addEventListener("click", () => openConversation(c.id));
      nav.appendChild(b);
    }
  }
  async function openConversation(id) {
    state.current = id;
    const conv = state.conversations.find((c) => c.id === id);
    $("conv-title").textContent = conv ? conv.title : "שיחה";
    renderConversations();
    const messages = await api(`/api/conversations/${id}/messages`);
    const box = $("messages"); box.innerHTML = "";
    for (const m of messages) addBubble(m.role, m.content, { hasImage: m.has_image, time: m.created_at });
    if (!messages.length) renderEmpty();
    scrollDown();
  }
  function renderEmpty() {
    $("messages").innerHTML = `<div class="empty"><img class="logo-lg" src="/static/logo.svg" alt="" width="64" height="64"><p>איך אפשר לעזור? אפשר לשאול על התקציב, או לצרף תמונת חשבונית.</p>`
      + HINTS.map((h) => `<span class="hint" tabindex="0" role="button">${escapeHtml(h)}</span>`).join("") + `</div>`;
    $("messages").querySelectorAll(".hint").forEach((h) => {
      const pick = () => { $("input").value = h.textContent; $("input").focus(); };
      h.addEventListener("click", pick);
      h.addEventListener("keydown", (e) => { if (e.key === "Enter" || e.key === " ") { e.preventDefault(); pick(); } });
    });
  }
  $("new-chat").addEventListener("click", () => { state.current = null; $("conv-title").textContent = "שיחה חדשה"; renderConversations(); renderEmpty(); $("input").focus(); });

  // ---------- messages ----------
  function addBubble(role, text, { hasImage = false, imageDataUrl = null, time = null } = {}) {
    const div = document.createElement("div");
    div.className = `msg ${role}`;
    const who = role === "user" ? (state.user ? state.user.name : "אני") : BOT_NAME;
    const avatar = role === "user" ? escapeHtml(who.trim().charAt(0).toUpperCase()) : `<img src="/static/logo.svg" alt="">`;
    const when = time ? new Date(time) : new Date();
    const stamp = when.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
    let inner = "";
    if (imageDataUrl) inner += `<img class="img" src="${imageDataUrl}" alt="חשבונית מצורפת">`;
    else if (hasImage) inner += `<span class="chip">📎 תמונה</span><br>`;
    inner += role === "user" ? `<p>${escapeHtml(text).replace(/\n/g, "<br>")}</p>` : render(text);
    div.innerHTML = `<div class="avatar ${role}">${avatar}</div><div class="msg-body"><div class="msg-head"><span class="author">${escapeHtml(who)}</span>${role === "assistant" ? '<span class="tag">עוזר</span>' : ""}<span class="time">${stamp}</span></div><div class="body" dir="auto">${inner}</div></div>`;
    $("messages").appendChild(div);
    scrollDown();
    return div;
  }

  // ---------- image attach ----------
  $("image").addEventListener("change", () => {
    const file = $("image").files[0];
    if (!file) { state.image = null; $("attachment").classList.add("hidden"); return; }
    if (file.size > 5 * 1024 * 1024) { alert("התמונה גדולה מ-5 מ״ב."); $("image").value = ""; return; }
    const reader = new FileReader();
    reader.onload = () => {
      const dataUrl = reader.result;
      state.image = { media_type: file.type, data: dataUrl.split(",")[1], dataUrl, name: file.name };
      $("attachment").textContent = `מצורף: ${file.name}`; $("attachment").classList.remove("hidden");
    };
    reader.readAsDataURL(file);
  });

  // ---------- send + stream ----------
  $("input").addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); $("composer").requestSubmit(); } });
  $("input").addEventListener("input", () => { const t = $("input"); t.dir = t.value ? "auto" : "rtl"; t.style.height = "auto"; t.style.height = Math.min(t.scrollHeight, 160) + "px"; });

  $("composer").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (state.streaming) return;
    const text = $("input").value.trim();
    if (!text && !state.image) return;
    const image = state.image;
    $("input").value = ""; $("input").dir = "rtl"; $("input").style.height = "auto"; state.image = null; $("image").value = ""; $("attachment").classList.add("hidden");
    if ($("messages").querySelector(".empty")) $("messages").innerHTML = "";
    addBubble("user", text || "(תמונת חשבונית)", { imageDataUrl: image ? image.dataUrl : null });

    const bot = addBubble("assistant", "");
    const body = bot.querySelector(".body"); body.classList.add("cursor");
    const meta = document.createElement("div"); meta.className = "meta"; bot.querySelector(".msg-body").appendChild(meta);
    state.streaming = true; $("send").disabled = true; setStatus("חושב…");
    let full = "";
    try {
      const res = await fetch("/api/chat", {
        method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ conversation_id: state.current, message: text, image: image ? { media_type: image.media_type, data: image.data } : null }),
      });
      if (!res.ok) { let d = res.statusText; try { d = (await res.json()).detail || d; } catch (_) {} throw new Error(d); }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data: ")); if (!line) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "meta") { state.current = ev.conversation_id; if (ev.title) $("conv-title").textContent = ev.title; }
          else if (ev.type === "text") { full += ev.text; body.innerHTML = render(full); followAnswer(bot); }
          else if (ev.type === "tool") {
            const label = TOOL_LABELS[ev.name] || ev.name;
            const c = document.createElement("span"); c.className = `chip tool ${ev.status}`;
            c.textContent = `${ev.status === "start" ? "⚙" : "✓"} ${label}${ev.status === "done" && ev.summary ? ": " + ev.summary : ""}`;
            meta.appendChild(c); setStatus(`משתמש ב${label}…`);
          }
          else if (ev.type === "done") { const u = ev.usage || {}; const c = document.createElement("span"); c.className = "chip"; c.dir = "ltr"; c.textContent = `${u.input_tokens || 0} in · ${u.output_tokens || 0} out · $${(ev.cost_usd || 0).toFixed(4)}`; meta.appendChild(c); }
          else if (ev.type === "error") { full += `\n\n**שגיאה:** ${ev.message}`; body.innerHTML = render(full); }
        }
      }
    } catch (err) {
      full += `\n\n**שגיאה:** ${err.message}`; body.innerHTML = render(full);
    } finally {
      body.classList.remove("cursor"); state.streaming = false; $("send").disabled = false; setStatus("");
      await loadConversationsQuiet();
    }
  });
  async function loadConversationsQuiet() { try { state.conversations = await api("/api/conversations"); renderConversations(); } catch (_) {} }

  // ---------- invoices panel ----------
  function invoiceRow(r) {
    const line = r.chapter ? `${escapeHtml(r.chapter)} / ${escapeHtml(r.sub_item || "")}` : "לא משויכת לסעיף";
    const reasons = (r.flag_reason || "").split(",").filter(Boolean).map((k) => REASON_LABELS[k] || k).join(", ");
    const status = STATUS_LABELS[r.status] || r.status;
    const amount = r.amount == null ? "—" : `${Number(r.amount).toLocaleString("he-IL")} ${r.currency === "ILS" ? "₪" : r.currency}`;
    return `<tr><td>${fmtDate(r.invoice_date || (r.created_at || "").slice(0, 10))}</td>`
      + `<td>${escapeHtml(r.supplier)}<small>${escapeHtml(r.invoice_number || "")}${r.invoice_number ? " · " : ""}${line}</small></td>`
      + `<td>${amount}</td>`
      + `<td><span class="badge ${escapeHtml(r.status)}">${escapeHtml(status)}</span>${r.flagged ? '<span class="badge flag">חריגה</span>' : ""}`
      + (reasons ? `<small>${escapeHtml(reasons)}</small>` : "") + `</td></tr>`;
  }
  async function loadInvoices() {
    const rows = await api("/api/invoices");
    $("invoice-rows").innerHTML = rows.map(invoiceRow).join("") || `<tr><td colspan="4"><small>אין חשבוניות עדיין.</small></td></tr>`;
  }
  $("toggle-invoices").addEventListener("click", async () => { $("invoices").classList.toggle("hidden"); if (!$("invoices").classList.contains("hidden")) await loadInvoices(); });
  $("close-invoices").addEventListener("click", () => $("invoices").classList.add("hidden"));

  // ---------- boot ----------
  (async () => {
    try { state.user = await api("/api/me"); showApp(); await loadConversations(); }
    catch (_) { showLogin(); }
  })();
})();
