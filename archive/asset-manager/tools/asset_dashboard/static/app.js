const state = {
  data: null,
  filtered: [],
  page: 1,
  pageSize: 80,
  kind: "",
};

const $ = (id) => document.getElementById(id);
const fmtBytes = (value) => {
  const units = ["B", "KB", "MB", "GB"];
  let n = Number(value || 0), i = 0;
  while (n >= 1024 && i < units.length - 1) { n /= 1024; i++; }
  return `${n.toFixed(i ? 1 : 0)} ${units[i]}`;
};
const esc = (value) => String(value ?? "").replace(/[&<>"']/g, c => ({
  "&":"&amp;", "<":"&lt;", ">":"&gt;", '"':"&quot;", "'":"&#39;"
}[c]));

async function request(url, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { "Content-Type": "application/json", ...(options.headers || {}) }
  });
  const payload = await response.json();
  if (!response.ok || !payload.ok) throw new Error(payload.error || response.statusText);
  return payload;
}

async function load() {
  const payload = await request("/api/state");
  state.data = payload.state;
  renderShell();
  applyFilters();
}

function renderShell() {
  const { summary, vault } = state.data;
  $("vaultPath").textContent = vault;
  $("mTotal").textContent = summary.total;
  $("mAvailable").textContent = summary.available;
  $("mTelegram").textContent = summary.telegramReady;
  $("mTelegramPercent").textContent = `${Math.round(summary.telegramReady / Math.max(summary.total, 1) * 100)}% tổng asset`;
  $("mBytes").textContent = fmtBytes(summary.totalBytes);
  $("mKinds").textContent = `${Object.keys(summary.kinds).length} loại`;
  $("navAll").textContent = summary.total;
  $("navText").textContent = summary.kinds["text-animation"] || 0;
  $("navVideo").textContent = summary.kinds["video-effect"] || 0;
  $("navTextFx").textContent = summary.kinds["text-effect"] || 0;
  $("navBubbles").textContent = summary.kinds["text-bubble"] || 0;
  $("navTemplates").textContent = summary.kinds["text-template"] || 0;
  $("navFonts").textContent = summary.kinds["font"] || 0;
  $("navModels").textContent = summary.kinds["effect-model"] || 0;
  $("navRuntime").textContent = summary.kinds["script-runtime"] || 0;
  $("navMedia").textContent = summary.kinds["media"] || 0;

  const kindSelect = $("kindFilter");
  kindSelect.innerHTML = '<option value="">Mọi loại</option>' +
    Object.entries(summary.kinds).map(([kind, count]) =>
      `<option value="${esc(kind)}">${esc(kind)} (${count})</option>`).join("");
  const categories = [...new Set(state.data.assets
    .filter(x => x.kind === "text-animation")
    .map(x => x.category).filter(Boolean))].sort();
  $("categoryFilter").innerHTML = '<option value="">Mọi category</option>' +
    categories.map(c => `<option>${esc(c)}</option>`).join("");
}

function applyFilters() {
  if (!state.data) return;
  const q = $("search").value.trim().toLowerCase();
  const kind = state.kind || $("kindFilter").value;
  const category = $("categoryFilter").value;
  const status = $("statusFilter").value;
  state.filtered = state.data.assets.filter(asset => {
    if (kind && asset.kind !== kind) return false;
    if (category && asset.category !== category) return false;
    if (status === "available" && !asset.available) return false;
    if (status === "telegram" && !asset.telegram?.ready) return false;
    if (status === "missing-telegram" && asset.telegram?.ready) return false;
    if (status === "missing" && asset.status !== "missing") return false;
    if (q) {
      const haystack = `${asset.name} ${asset.effectId} ${asset.category} ${asset.assetId}`.toLowerCase();
      if (!haystack.includes(q)) return false;
    }
    return true;
  });
  state.page = 1;
  renderRows();
}

function renderRows() {
  const pages = Math.max(1, Math.ceil(state.filtered.length / state.pageSize));
  state.page = Math.min(state.page, pages);
  const start = (state.page - 1) * state.pageSize;
  const rows = state.filtered.slice(start, start + state.pageSize);
  $("resultCount").textContent = state.filtered.length;
  $("pageLabel").textContent = `${state.page} / ${pages}`;
  $("prevPage").disabled = state.page <= 1;
  $("nextPage").disabled = state.page >= pages;
  $("assetRows").innerHTML = rows.map(asset => {
    const tg = asset.telegram?.ready;
    const thumb = asset.thumbUrl || asset.previewUrl;
    return `<tr data-id="${esc(asset.assetId)}">
      <td><div class="asset-main">${thumb
        ? `<img class="asset-thumb" loading="lazy" src="${esc(thumb)}" alt="">`
        : '<span class="asset-thumb placeholder">◈</span>'}
        <div><div class="asset-name">${esc(asset.name)}</div><div class="asset-id">${esc(asset.effectId || asset.assetId)}</div></div>
      </div></td>
      <td><span class="badge kind">${esc(asset.kind)}</span></td>
      <td>${esc(asset.category || "—")}</td>
      <td>${fmtBytes(asset.bytes)}</td>
      <td><span class="badge ${tg ? "telegram" : "missing"}">${tg ? "Đã có" : "Chưa có"}</span></td>
      <td><span class="badge ${esc(asset.status)}">${esc(asset.status)}</span></td>
    </tr>`;
  }).join("") || '<tr><td colspan="6" class="muted">Không có asset khớp bộ lọc.</td></tr>';
  document.querySelectorAll("tr[data-id]").forEach(row => {
    row.addEventListener("click", () => openDetail(row.dataset.id));
  });
}

function openDetail(assetId) {
  const asset = state.data.assets.find(item => item.assetId === assetId);
  if (!asset) return;
  $("detailKind").textContent = asset.kind;
  $("detailName").textContent = asset.name;
  const fields = [
    ["Asset ID", asset.assetId], ["Effect ID", asset.effectId || "—"],
    ["Resource ID", asset.resourceId || "—"], ["Category", asset.category || "—"],
    ["Kích thước", fmtBytes(asset.bytes)], ["Local", asset.available ? "Có" : "Không"],
    ["Telegram", asset.telegram?.ready ? "Đã có file_id" : "Chưa có"],
    ["file_id", asset.telegram?.fileId || "—"], ["Đường dẫn", asset.localPath || "—"],
    ["SHA-256", asset.sha256 || "—"], ["Preview", asset.previewUrl || "—"],
  ];
  $("detailGrid").innerHTML = fields.map(([k,v]) =>
    `<dt>${esc(k)}</dt><dd>${esc(v)}</dd>`).join("");
  const previewBox = $("detailPreview");
  const previewImage = $("detailPreviewImg");
  if (asset.previewUrl) {
    previewImage.src = asset.previewUrl;
    previewBox.hidden = false;
  } else {
    previewImage.removeAttribute("src");
    previewBox.hidden = true;
  }
  $("detailJson").textContent = JSON.stringify(asset, null, 2);
  $("drawer").classList.add("open");
  $("drawerBackdrop").classList.add("open");
}

function closeDrawer() {
  $("drawer").classList.remove("open");
  $("drawerBackdrop").classList.remove("open");
}

async function scan() {
  const button = $("btnScan");
  button.disabled = true; button.textContent = "Đang quét…";
  try {
    const payload = await request("/api/scan", { method: "POST", body: "{}" });
    state.data = payload.state;
    renderShell(); applyFilters();
  } catch (error) { alert(`Scan lỗi: ${error.message}`); }
  finally { button.disabled = false; button.textContent = "Quét lại"; }
}

async function telegramReload() {
  const button = $("btnTelegram");
  button.disabled = true;
  try {
    const payload = await request("/api/telegram/reload", { method: "POST", body: "{}" });
    state.data = payload.state; renderShell(); applyFilters();
  } catch (error) { alert(`Đồng bộ lỗi: ${error.message}`); }
  finally { button.disabled = false; }
}

document.querySelectorAll(".nav-item").forEach(button => {
  button.addEventListener("click", () => {
    document.querySelectorAll(".nav-item").forEach(x => x.classList.remove("active"));
    button.classList.add("active");
    state.kind = button.dataset.kind;
    $("kindFilter").value = state.kind;
    applyFilters();
  });
});
$("search").addEventListener("input", applyFilters);
$("kindFilter").addEventListener("change", () => { state.kind = $("kindFilter").value; applyFilters(); });
$("categoryFilter").addEventListener("change", applyFilters);
$("statusFilter").addEventListener("change", applyFilters);
$("prevPage").addEventListener("click", () => { state.page--; renderRows(); });
$("nextPage").addEventListener("click", () => { state.page++; renderRows(); });
$("btnScan").addEventListener("click", scan);
$("btnTelegram").addEventListener("click", telegramReload);
$("drawerClose").addEventListener("click", closeDrawer);
$("drawerBackdrop").addEventListener("click", closeDrawer);
$("btnAdd").addEventListener("click", () => $("addDialog").showModal());
$("addClose").addEventListener("click", () => $("addDialog").close());
$("addForm").addEventListener("submit", async event => {
  event.preventDefault();
  const form = new FormData(event.target);
  const payload = Object.fromEntries(form.entries());
  payload.copy = form.has("copy");
  try {
    $("formError").textContent = "";
    const result = await request("/api/asset", {
      method: "POST", body: JSON.stringify(payload)
    });
    state.data = result.state;
    $("addDialog").close();
    event.target.reset();
    renderShell(); applyFilters();
  } catch (error) { $("formError").textContent = error.message; }
});

load().catch(error => {
  document.body.innerHTML = `<pre style="padding:24px;color:#ff6b7c">${esc(error.stack || error.message)}</pre>`;
});
