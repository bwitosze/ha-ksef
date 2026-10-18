// Panel "KSeF" w menu bocznym Home Assistanta.
//
// Czysty Web Component bez Lita i bez bundlera - HA nie gwarantuje panelom
// dostępu do swojej kopii Lita, a plik ma się dać edytować na H: bez budowania.
// Dane bierze z komendy WebSocket `ksef/invoices`, którą wystawia integracja.
// Pobieranie plików idzie przez `auth/sign_path`: zwykły link <a href> nie
// niesie nagłówka Authorization, a podpisana ścieżka działa bez niego przez
// ~30 sekund i tylko dla tego jednego pliku.

const STYLE = `
  :host {
    display: block;
    min-height: 100%;
    background: var(--primary-background-color);
    color: var(--primary-text-color);
    font-family: var(--paper-font-body1_-_font-family, Roboto, sans-serif);
  }
  .toolbar {
    display: flex;
    align-items: center;
    gap: 8px;
    height: var(--header-height, 56px);
    padding: 0 12px;
    box-sizing: border-box;
    background: var(--app-header-background-color, var(--primary-color));
    color: var(--app-header-text-color, var(--text-primary-color, #fff));
    border-bottom: var(--app-header-border-bottom, none);
  }
  .toolbar .title { flex: 1; font-size: 20px; font-weight: 400; }
  .toolbar button {
    display: inline-flex; align-items: center; gap: 6px;
    background: transparent; color: inherit;
    border: 1px solid currentColor; border-radius: 18px;
    padding: 6px 14px; font: inherit; font-size: 14px; cursor: pointer;
  }
  .toolbar button[disabled] { opacity: .5; cursor: default; }
  /* Układ zależy od szerokości panelu, nie okna: przy otwartym menu bocznym
     HA panel bywa dużo węższy niż ekran, więc @media tu nie wystarcza. */
  .content {
    max-width: 1100px; margin: 0 auto; padding: 16px; box-sizing: border-box;
    container-type: inline-size;
  }
  .tabs { position: relative; display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .tabs + .tabs { margin-bottom: 16px; }
  .tab {
    background: var(--card-background-color);
    color: var(--primary-text-color);
    border: 1px solid var(--divider-color);
    border-radius: 18px; padding: 6px 16px;
    font: inherit; font-size: 14px; cursor: pointer;
  }
  .tab.active {
    background: var(--primary-color);
    color: var(--text-primary-color, #fff);
    border-color: var(--primary-color);
  }
  .tab .count { opacity: .75; margin-left: 4px; }
  .card {
    background: var(--card-background-color);
    border-radius: var(--ha-card-border-radius, 12px);
    border: var(--ha-card-border-width, 1px) solid var(--ha-card-border-color, var(--divider-color));
    /* auto zamiast hidden: gdyby tabela mimo wszystko się nie zmieściła,
       da się ją przewinąć, zamiast tracić kolumny po prawej. */
    overflow: auto;
  }
  table { width: 100%; border-collapse: collapse; font-size: 14px; }
  th, td { padding: 10px 12px; text-align: left; border-bottom: 1px solid var(--divider-color); }
  th { font-weight: 500; color: var(--secondary-text-color); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
  td.num, th.num { text-align: right; white-space: nowrap; font-variant-numeric: tabular-nums; }
  td.date { white-space: nowrap; }
  td.dl { white-space: nowrap; text-align: right; }
  tr:last-child td { border-bottom: none; }
  .party { font-weight: 500; }
  .sub { color: var(--secondary-text-color); font-size: 12px; margin-top: 2px; word-break: break-all; }
  .dl button {
    background: transparent; color: var(--primary-color);
    border: 1px solid var(--divider-color); border-radius: 14px;
    padding: 4px 10px; margin-left: 6px; min-width: 48px;
    font: inherit; font-size: 13px; font-weight: 500; cursor: pointer;
  }
  .dl button:hover { border-color: var(--primary-color); }
  .dl button[disabled] { opacity: .6; cursor: default; }
  .badge {
    display: inline-block; font-size: 11px; padding: 1px 6px; border-radius: 8px;
    background: var(--secondary-background-color); color: var(--secondary-text-color);
    margin-left: 6px; vertical-align: middle;
  }
  .badge.env {
    background: rgba(var(--rgb-warning-color, 255, 166, 0), .18);
    color: var(--warning-color, #ffa600); font-weight: 500;
  }
  .footer {
    display: flex; flex-wrap: wrap; justify-content: space-between; gap: 8px;
    padding: 12px; font-size: 13px; color: var(--secondary-text-color);
    border-top: 1px solid var(--divider-color);
  }
  .footer strong { color: var(--primary-text-color); }
  .empty { padding: 32px 16px; text-align: center; color: var(--secondary-text-color); }
  .error {
    margin-bottom: 12px; padding: 10px 14px; border-radius: 8px;
    background: rgba(var(--rgb-error-color, 219, 68, 55), .12);
    color: var(--error-color, #db4437); font-size: 14px;
  }
  @media (max-width: 700px) {
    .content { padding: 8px; }
    .toolbar button { padding: 6px 10px; }
  }
  @container (max-width: 900px) {
    th.hide-narrow, td.hide-narrow { display: none; }
    th, td { padding: 8px; }
  }
  /* Telefon i wąski panel: każda faktura jako karta.
       kontrahent      brutto
       numer / KSeF    data
       [ PDF ]  [ XML ]
     Netto znika (jest w sumie pod listą). */
  @container (max-width: 640px) {
    .tabs.months { flex-wrap: nowrap; overflow-x: auto; scrollbar-width: none; padding-bottom: 2px; }
    .tabs.months::-webkit-scrollbar { display: none; }
    .tabs.months .tab { flex: none; }
    table, tbody { display: block; }
    thead { display: none; }
    tr {
      display: grid; grid-template-columns: minmax(0, 1fr) auto;
      column-gap: 12px; row-gap: 4px;
      padding: 12px; border-bottom: 1px solid var(--divider-color);
    }
    tr:last-child { border-bottom: none; }
    td { display: block; padding: 0; border: none; }
    /* Bez tego długie słowo bez spacji (nazwa firmy, numer) wyjeżdża poza
       kolumnę i wchodzi pod kwotę brutto. */
    td.who, td.no { overflow-wrap: anywhere; }
    td.who { grid-column: 1; grid-row: 1; }
    td.gross { grid-column: 2; grid-row: 1; font-weight: 500; }
    td.no { grid-column: 1; grid-row: 2; }
    td.date { grid-column: 2; grid-row: 2; text-align: right; font-size: 13px; color: var(--secondary-text-color); }
    td.dl { grid-column: 1 / -1; grid-row: 3; display: flex; gap: 8px; margin-top: 6px; }
    .dl button { flex: 1; margin: 0; padding: 9px 10px; font-size: 14px; }
  }
`;

const KIND_LABELS = { purchase: "Zakupowe", sales: "Sprzedażowe" };

function esc(value) {
  return String(value ?? "").replace(/[&<>"']/g, (c) => ({
    "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;",
  })[c]);
}

function money(value, currency) {
  if (value === null || value === undefined || value === "") return "—";
  const num = Number(value);
  if (Number.isNaN(num)) return esc(value);
  const text = num.toLocaleString("pl-PL", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  return currency && currency !== "PLN" ? `${text} ${esc(currency)}` : text;
}

function shortDate(iso) {
  if (!iso) return "—";
  const [y, m, d] = String(iso).slice(0, 10).split("-");
  return d && m ? `${d}.${m}.${y}` : esc(iso);
}

function dateTime(iso) {
  if (!iso) return "nigdy";
  const dt = new Date(iso);
  if (Number.isNaN(dt.getTime())) return esc(iso);
  return dt.toLocaleString("pl-PL", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

class KsefPanel extends HTMLElement {
  constructor() {
    super();
    this.attachShadow({ mode: "open" });
    this._kind = "purchase";
    this._month = null;
    this._data = null;
    this._error = null;
    this._loading = false;
    this._refreshing = false;
    this._unsub = null;
  }

  set hass(hass) {
    const first = !this._hass;
    this._hass = hass;
    if (this._menuButton) this._menuButton.hass = hass;
    if (first) this._init();
  }

  set narrow(narrow) {
    this._narrow = narrow;
    if (this._menuButton) this._menuButton.narrow = narrow;
  }

  set panel(panel) {
    this._panel = panel;
  }

  connectedCallback() {
    if (this._hass && !this._unsub) this._subscribe();
  }

  disconnectedCallback() {
    if (this._unsub) {
      this._unsub.then((unsub) => unsub()).catch(() => {});
      this._unsub = null;
    }
  }

  async _init() {
    this._render();
    await this._load();
    this._subscribe();
  }

  // Integracja daje znać po każdym odświeżeniu - panel otwarty na stałe
  // na tablecie nie musi być przeładowywany ręcznie. Własna komenda
  // `ksef/subscribe` zamiast subscribeEvents: HA odrzuca subskrypcję zdarzeń
  // spoza listy dozwolonych dla kont bez uprawnień administratora.
  _subscribe() {
    if (this._unsub || !this._hass?.connection) return;
    const sub = this._hass.connection.subscribeMessage(() => this._load(), { type: "ksef/subscribe" });
    this._unsub = sub;
    sub.catch(() => {
      // Np. starsza wersja integracji po stronie serwera - zwolnij miejsce,
      // żeby kolejne podłączenie panelu mogło spróbować ponownie.
      if (this._unsub === sub) this._unsub = null;
    });
  }

  async _load() {
    if (this._loading) return;
    this._loading = true;
    try {
      this._data = await this._hass.callWS({ type: "ksef/invoices" });
      this._error = null;
      const months = this._data.months || [];
      if (!this._month || !months.some((m) => m.key === this._month)) {
        // Domyślnie bieżący miesiąc - ostatni na liście.
        this._month = months.length ? months[months.length - 1].key : null;
      }
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._loading = false;
      this._render();
    }
  }

  async _refresh() {
    if (this._refreshing) return;
    this._refreshing = true;
    this._render();
    try {
      await this._hass.callWS({ type: "ksef/refresh" });
      await this._load();
    } catch (err) {
      this._error = err?.message || String(err);
    } finally {
      this._refreshing = false;
      this._render();
    }
  }

  async _signedXmlUrl(entryId, ksefNumber) {
    const path = `/api/ksef/${encodeURIComponent(entryId)}/${encodeURIComponent(ksefNumber)}.xml`;
    const signed = await this._hass.callWS({ type: "auth/sign_path", path, expires: 60 });
    return signed.path;
  }

  _save(href, filename) {
    const a = document.createElement("a");
    a.href = href;
    a.download = filename;
    a.rel = "noopener";
    document.body.appendChild(a);
    a.click();
    a.remove();
  }

  async _download(entryId, ksefNumber, format) {
    const key = `${ksefNumber}.${format}`;
    if (this._busy?.has(key)) return;
    this._busy = this._busy || new Set();
    this._busy.add(key);
    this._render();
    try {
      const url = await this._signedXmlUrl(entryId, ksefNumber);
      // XML też przez fetch: przy błędzie (np. 429 - limit KSeF) pokazujemy
      // komunikat, zamiast zapisać go na dysku jako plik .xml.
      const resp = await fetch(url);
      if (!resp.ok) throw new Error(await resp.text() || `HTTP ${resp.status}`);
      const xmlBlob = await resp.blob();
      if (format === "xml") {
        const objectUrl = URL.createObjectURL(xmlBlob);
        this._save(objectUrl, `${ksefNumber}.xml`);
        setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
        return;
      }
      // PDF składa oficjalny generator MF (CIRFMF/ksef-pdf-generator) w
      // przeglądarce. Moduł ma ~3,5 MB, więc ładujemy go dopiero tutaj.
      const xml = new File([xmlBlob], `${ksefNumber}.xml`, { type: "application/xml" });
      const base = this._panel?.config?.static_url || "/ksef_static";
      const version = this._panel?.config?.version || "";
      const lib = await import(`${base}/ksef-pdf-generator.js?v=${version}`);
      const inv = this._findInvoice(ksefNumber);
      const extra = { nrKSeF: ksefNumber };
      if (inv?.qr_url) extra.qrCode = inv.qr_url;
      if (inv?.acquisition_date) extra.acDate = shortDate(inv.acquisition_date);
      const blob = await lib.generateInvoice(xml, extra, "blob");
      const objectUrl = URL.createObjectURL(blob);
      this._save(objectUrl, `${(inv?.invoice_number || ksefNumber).replace(/[\\/:*?"<>|]+/g, "_")}.pdf`);
      setTimeout(() => URL.revokeObjectURL(objectUrl), 10000);
    } catch (err) {
      this._error = `Nie udało się pobrać ${format.toUpperCase()}: ${err?.message || err}`;
    } finally {
      this._busy.delete(key);
      this._render();
    }
  }

  _findInvoice(ksefNumber) {
    for (const kind of Object.keys(KIND_LABELS)) {
      const hit = (this._data?.invoices?.[kind] || []).find((inv) => inv.ksef_number === ksefNumber);
      if (hit) return hit;
    }
    return null;
  }

  _link(format, inv) {
    const busy = this._busy?.has(`${inv.ksef_number}.${format}`);
    // <button>, nie <a> bez href: tylko przycisk jest fokusowalny i na
    // telefonie dostaje normalną obsługę dotyku.
    return `<button data-dl="${format}" data-entry="${esc(inv.entry_id)}" data-ksef="${esc(inv.ksef_number)}"${busy ? " disabled" : ""}>${busy ? "…" : format.toUpperCase()}</button>`;
  }

  _invoices() {
    const all = this._data?.invoices?.[this._kind] || [];
    return all.filter((inv) => inv.month === this._month);
  }

  _countFor(kind, month) {
    const all = this._data?.invoices?.[kind] || [];
    return all.filter((inv) => inv.month === month).length;
  }

  _render() {
    const root = this.shadowRoot;
    const data = this._data;
    const months = data?.months || [];
    const invoices = this._invoices();
    const mixed = !!data?.mixed_environments;

    const kindTabs = Object.entries(KIND_LABELS).map(([key, label]) => `
      <button class="tab ${key === this._kind ? "active" : ""}" data-kind="${key}">
        ${label}<span class="count">${this._month ? this._countFor(key, this._month) : ""}</span>
      </button>`).join("");

    const monthTabs = months.map((m) => `
      <button class="tab ${m.key === this._month ? "active" : ""}" data-month="${esc(m.key)}">
        ${esc(m.label)}
      </button>`).join("");

    const partyHeader = this._kind === "purchase" ? "Sprzedawca" : "Nabywca";

    let body;
    if (!data && !this._error) {
      body = `<div class="empty">Wczytywanie…</div>`;
    } else if (!data?.entries?.length) {
      body = `<div class="empty">Integracja KSeF nie jest skonfigurowana.</div>`;
    } else if (!invoices.length) {
      body = `<div class="empty">Brak faktur w tym miesiącu.</div>`;
    } else {
      const rows = invoices.map((inv) => `
        <tr>
          <td class="date">${shortDate(inv.issue_date)}</td>
          <td class="who">
            <div class="party">${esc(inv.counterparty_name || "—")}${inv.invoice_type && inv.invoice_type !== "Vat" ? `<span class="badge">${esc(inv.invoice_type)}</span>` : ""}${mixed && inv.environment !== "prod" ? `<span class="badge env">${esc(String(inv.environment).toUpperCase())}</span>` : ""}</div>
            <div class="sub">${inv.counterparty_nip ? `NIP ${esc(inv.counterparty_nip)}` : ""}</div>
          </td>
          <td class="no">
            <div>${esc(inv.invoice_number)}</div>
            <div class="sub">${esc(inv.ksef_number)}</div>
          </td>
          <td class="num hide-narrow">${money(inv.net_amount, inv.currency)}</td>
          <td class="num gross">${money(inv.gross_amount, inv.currency)}</td>
          <td class="dl">
            ${this._link("pdf", inv)}
            ${this._link("xml", inv)}
          </td>
        </tr>`).join("");

      // Sumy tylko dla PLN - faktury walutowe pokazujemy, ale nie mieszamy kwot.
      // Przy wpisie produkcyjnym i testowym naraz sumujemy samą produkcję.
      const counted = mixed ? invoices.filter((inv) => inv.environment === "prod") : invoices;
      const pln = counted.filter((inv) => !inv.currency || inv.currency === "PLN");
      const sum = (key) => pln.reduce((acc, inv) => acc + (Number(inv[key]) || 0), 0);
      const foreign = counted.length - pln.length;
      const skippedEnv = invoices.length - counted.length;

      body = `
        <table>
          <thead><tr>
            <th>Data</th><th>${partyHeader}</th><th>Numer</th>
            <th class="num hide-narrow">Netto</th><th class="num">Brutto</th><th></th>
          </tr></thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="footer">
          <span>Razem: <strong>${invoices.length}</strong> ·
            netto <strong>${money(sum("net_amount"))}</strong> ·
            brutto <strong>${money(sum("gross_amount"))} zł</strong>
            ${foreign ? ` (bez ${foreign} walutowych)` : ""}
            ${skippedEnv ? ` (bez ${skippedEnv} testowych)` : ""}</span>
        </div>`;
    }

    const status = data ? `
      <div class="footer" style="border-top:none;padding:8px 4px">
        <span>Ostatnie odświeżenie: ${dateTime(data.last_update)}${data.environment && data.environment !== "prod" ? ` · środowisko <strong>${esc(data.environment)}</strong>` : ""}</span>
      </div>` : "";

    const errors = [this._error, data?.last_error].filter(Boolean)
      .map((e) => `<div class="error">${esc(e)}</div>`).join("");

    root.innerHTML = `
      <style>${STYLE}</style>
      <div class="toolbar">
        <span id="menu"></span>
        <span class="title">KSeF</span>
        <button id="refresh" ${this._refreshing ? "disabled" : ""}>
          ${this._refreshing ? "Odświeżanie…" : "⟳ Odśwież"}
        </button>
      </div>
      <div class="content">
        ${errors}
        <div class="tabs">${kindTabs}</div>
        <div class="tabs months">${monthTabs}</div>
        <div class="card">${body}</div>
        ${status}
      </div>`;

    // Przycisk menu bocznego (hamburger) na wąskich ekranach - element HA.
    this._menuButton = document.createElement("ha-menu-button");
    this._menuButton.hass = this._hass;
    this._menuButton.narrow = this._narrow;
    root.getElementById("menu").appendChild(this._menuButton);

    // Na telefonie miesiące są jednym przewijanym paskiem - pokaż wybrany
    // (domyślnie ostatni). scrollLeft, nie scrollIntoView: ten drugi
    // przewinąłby też całą stronę do góry przy każdym odświeżeniu danych.
    const strip = root.querySelector(".tabs.months");
    const active = strip?.querySelector(".tab.active");
    if (active && strip.scrollWidth > strip.clientWidth) {
      strip.scrollLeft = active.offsetLeft - (strip.clientWidth - active.offsetWidth) / 2;
    }

    root.getElementById("refresh").addEventListener("click", () => this._refresh());
    root.querySelectorAll("[data-kind]").forEach((el) =>
      el.addEventListener("click", () => { this._kind = el.dataset.kind; this._render(); }));
    root.querySelectorAll("[data-month]").forEach((el) =>
      el.addEventListener("click", () => { this._month = el.dataset.month; this._render(); }));
    root.querySelectorAll("[data-dl]").forEach((el) =>
      el.addEventListener("click", () => this._download(el.dataset.entry, el.dataset.ksef, el.dataset.dl)));
  }
}

customElements.define("ksef-panel", KsefPanel);
