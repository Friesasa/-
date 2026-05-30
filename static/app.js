const state = {
  task: null,
  selectedRow: 0,
  token: localStorage.getItem("authToken") || "",
  user: readStoredObject("currentUser"),
  frozenColumnCount: Number(localStorage.getItem("frozenColumnCount") || 0),
  columnWidthsByTask: readStoredObject("columnWidthsByTask"),
  rowHeightsByTask: readStoredObject("rowHeightsByTask"),
};

const $ = (id) => document.getElementById(id);

function readStoredObject(key) {
  try {
    return JSON.parse(localStorage.getItem(key) || "{}");
  } catch {
    return {};
  }
}

function setStatus(message) {
  $("status").textContent = message || "";
}

async function api(path, options = {}) {
  const headers = new Headers(options.headers || {});
  if (state.token && !options.noAuth) {
    headers.set("Authorization", `Bearer ${state.token}`);
  }
  const response = await fetch(path, { ...options, headers });
  if (!response.ok) {
    const text = await response.text();
    let message = text;
    try {
      message = JSON.parse(text).detail || text;
    } catch {
      // Keep the raw response body.
    }
    if (response.status === 401 && !options.noAuth) {
      clearSession();
      showSignedOut();
    }
    throw new Error(message || `请求失败：${response.status}`);
  }
  const contentType = response.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return response.json();
  }
  return response;
}

async function uploadForm(form, url) {
  const formData = new FormData(form);
  return api(url, { method: "POST", body: formData });
}

function setSession(data) {
  state.token = data.token;
  state.user = data.user;
  localStorage.setItem("authToken", data.token);
  localStorage.setItem("currentUser", JSON.stringify(data.user));
}

function clearSession() {
  state.token = "";
  state.user = {};
  state.task = null;
  localStorage.removeItem("authToken");
  localStorage.removeItem("currentUser");
}

function showAuthenticated() {
  $("authShell").classList.add("hidden");
  $("appShell").classList.remove("hidden");
  $("currentUser").textContent = state.user?.username ? `当前账号：${state.user.username}` : "";
}

function showSignedOut() {
  $("appShell").classList.add("hidden");
  $("authShell").classList.remove("hidden");
  $("taskMeta").textContent = "";
  $("editor").innerHTML = "";
}

function authPayloadFromForm(form) {
  const formData = new FormData(form);
  return {
    username: String(formData.get("username") || "").trim(),
    password: String(formData.get("password") || ""),
    invite_code: String(formData.get("invite_code") || "").trim() || null,
  };
}

async function bootstrap() {
  if (!state.token) {
    showSignedOut();
    return;
  }
  try {
    const data = await api("/api/auth/me");
    state.user = data.user;
    localStorage.setItem("currentUser", JSON.stringify(data.user));
    showAuthenticated();
    await refreshTasks();
    await refreshRatecardStatus();
  } catch (error) {
    showSignedOut();
  }
}

function formatDateTime(value) {
  if (!value) return "";
  const normalized = String(value).includes("T") ? value : String(value).replace(" ", "T");
  const date = new Date(normalized);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("zh-CN", { hour12: false });
}

async function refreshRatecardStatus() {
  const status = $("ratecardStatus");
  if (!status) return;
  try {
    const data = await api("/api/ratecards/latest");
    const ratecard = data.ratecard;
    if (!ratecard) {
      status.className = "uploadStatus empty";
      status.textContent = "尚未上传刊例";
      return;
    }
    status.className = "uploadStatus ready";
    status.textContent = `已上传：${formatDateTime(ratecard.created_at)}；达人 ${ratecard.talent_count} 个`;
    status.title = ratecard.filename || "";
  } catch (error) {
    status.className = "uploadStatus empty";
    status.textContent = "刊例状态读取失败";
  }
}

async function refreshTasks(selectedId) {
  const data = await api("/api/tasks");
  const select = $("taskSelect");
  select.innerHTML = "";
  for (const task of data.items) {
    const option = document.createElement("option");
    option.value = task.id;
    option.textContent = `#${task.id} ${task.brand_name || task.filename}`;
    select.appendChild(option);
  }
  if (selectedId) {
    select.value = selectedId;
  }
  if (select.value) {
    await loadTask(select.value);
  } else {
    state.task = null;
    renderTask();
  }
}

async function loadTask(taskId) {
  const data = await api(`/api/tasks/${taskId}`);
  state.task = data.task;
  state.selectedRow = 0;
  state.confirmedTalentMatch = null;
  renderTask();
}

function renderTask() {
  const task = state.task;
  if (!task) {
    $("taskMeta").textContent = "还没有选择任务。";
    $("editor").innerHTML = "";
    return;
  }
  $("taskMeta").textContent = `当前任务：${task.brand_name || task.filename}；工作表：${task.sheet_name}；表头行：${task.header_row}`;
  syncFreezeInput();
  renderMissing();
  renderTable();
}

function renderMissing() {
  const missing = state.task?.missing || {};
  const panel = $("missingPanel");
  panel.innerHTML = "";
  const rowMissing = missing[String(state.selectedRow)] || [];
  if (!rowMissing.length) {
    const ok = document.createElement("span");
    ok.textContent = "当前行无缺失标注";
    panel.appendChild(ok);
    return;
  }
  for (const item of rowMissing) {
    const badge = document.createElement("span");
    badge.textContent = `待补充：${item}`;
    panel.appendChild(badge);
  }
}

function renderTable() {
  const table = $("editor");
  const task = state.task;
  const headers = [
    '<thead><tr><th data-freeze-col="0">行</th>',
    ...task.columns.map((column, columnIndex) => {
      const hint = column.standard_label ? `<span class="fieldHint">${column.standard_label} · ${Math.round(column.confidence * 100)}%</span>` : "";
      return `<th data-freeze-col="${columnIndex + 1}"><div class="headerCellContent">${escapeHtml(column.header)}${hint}</div><span class="columnResizeHandle" data-column-index="${columnIndex + 1}"></span></th>`;
    }),
    "</tr></thead>",
  ].join("");
  const body = task.rows
    .map((row, rowIndex) => {
      const active = rowIndex === state.selectedRow ? "active" : "";
      const synced = isSyncedRow(row) ? "syncedRow" : "";
      const missingHeaders = new Set((task.missing || {})[String(rowIndex)] || []);
      const cells = task.columns
        .map((column, columnIndex) => {
          const value = row.values[column.key] ?? "";
          const missingClass = missingHeaders.has(column.header) ? "missingCell" : "";
          return `<td class="${missingClass}" data-freeze-col="${columnIndex + 1}" data-row-index="${rowIndex}"><input data-row="${rowIndex}" data-key="${column.key}" value="${escapeAttribute(value)}" /></td>`;
        })
        .join("");
      return `<tr class="${[active, synced].filter(Boolean).join(" ")}" data-row="${rowIndex}"><td data-freeze-col="0" data-row-index="${rowIndex}" class="rowNumberCell">${rowIndex + 1}<span class="rowResizeHandle" data-row-index="${rowIndex}"></span></td>${cells}</tr>`;
    })
    .join("");
  table.innerHTML = `${headers}<tbody>${body}</tbody>`;
  applyManualTableLayout();
  applyFrozenColumns();
  attachResizeHandlers();
  table.querySelectorAll("tbody tr").forEach((tr) => {
    tr.addEventListener("click", (event) => {
      state.selectedRow = Number(tr.dataset.row);
      if (event.target instanceof HTMLInputElement) {
        updateActiveRow();
        renderMissing();
        return;
      }
      renderTask();
    });
  });
  table.querySelectorAll("input").forEach((input) => {
    input.addEventListener("input", () => {
      const rowIndex = Number(input.dataset.row);
      const key = input.dataset.key;
      state.task.rows[rowIndex].values[key] = input.value;
    });
    input.addEventListener("change", () => {
      const rowIndex = Number(input.dataset.row);
      const key = input.dataset.key;
      state.task.rows[rowIndex].values[key] = input.value;
      state.task.missing = computeMissingClient(state.task);
      renderTask();
    });
  });
}

function isSyncedRow(row) {
  const source = row.source || {};
  return Boolean(row.inquiry_parse) || Object.values(source).some(Boolean);
}

function syncFreezeInput() {
  const input = $("freezeColumns");
  if (input && input.value !== String(state.frozenColumnCount || "")) {
    input.value = state.frozenColumnCount || "";
  }
}

function parseFrozenColumnIndexes(count, maxColumns) {
  const indexes = new Set([0]);
  const frozenCount = Math.max(0, Math.min(Number(count) || 0, maxColumns));
  for (let column = 1; column <= frozenCount; column += 1) {
    indexes.add(column);
  }
  return [...indexes].sort((a, b) => a - b);
}

function applyFrozenColumns() {
  const table = $("editor");
  const frozenColumns = parseFrozenColumnIndexes(state.frozenColumnCount, state.task?.columns?.length || 0);
  let left = 0;
  for (const columnIndex of frozenColumns) {
    const cells = table.querySelectorAll(`[data-freeze-col="${columnIndex}"]`);
    if (!cells.length) continue;
    cells.forEach((cell) => {
      cell.classList.add("frozenCell");
      cell.style.left = `${left}px`;
      if (cell.tagName === "TH") {
        cell.classList.add("frozenHeader");
      }
    });
    left += cells[0].getBoundingClientRect().width;
  }
}

function taskLayoutKey() {
  return String(state.task?.id || state.task?.filename || "default");
}

function taskColumnWidths() {
  const key = taskLayoutKey();
  state.columnWidthsByTask[key] ||= {};
  return state.columnWidthsByTask[key];
}

function taskRowHeights() {
  const key = taskLayoutKey();
  state.rowHeightsByTask[key] ||= {};
  return state.rowHeightsByTask[key];
}

function persistTableLayout() {
  localStorage.setItem("columnWidthsByTask", JSON.stringify(state.columnWidthsByTask));
  localStorage.setItem("rowHeightsByTask", JSON.stringify(state.rowHeightsByTask));
}

function applyManualTableLayout() {
  for (const [columnIndex, width] of Object.entries(taskColumnWidths())) {
    applyColumnWidth(columnIndex, width);
  }
  for (const [rowIndex, height] of Object.entries(taskRowHeights())) {
    applyRowHeight(rowIndex, height);
  }
}

function applyColumnWidth(columnIndex, width) {
  $("editor").querySelectorAll(`[data-freeze-col="${columnIndex}"]`).forEach((cell) => {
    cell.style.width = `${width}px`;
    cell.style.minWidth = `${width}px`;
    cell.style.maxWidth = `${width}px`;
  });
}

function applyRowHeight(rowIndex, height) {
  $("editor").querySelectorAll(`[data-row-index="${rowIndex}"]`).forEach((cell) => {
    cell.style.height = `${height}px`;
    const input = cell.querySelector("input");
    if (input) {
      input.style.minHeight = `${height}px`;
    }
  });
}

function setColumnWidth(columnIndex, width) {
  const nextWidth = Math.max(64, Math.min(640, Math.round(width)));
  taskColumnWidths()[String(columnIndex)] = nextWidth;
  applyColumnWidth(columnIndex, nextWidth);
  applyFrozenColumns();
  persistTableLayout();
}

function setRowHeight(rowIndex, height) {
  const nextHeight = Math.max(26, Math.min(180, Math.round(height)));
  taskRowHeights()[String(rowIndex)] = nextHeight;
  applyRowHeight(rowIndex, nextHeight);
  persistTableLayout();
}

function attachResizeHandlers() {
  $("editor").querySelectorAll(".columnResizeHandle").forEach((handle) => {
    handle.addEventListener("mousedown", startColumnResize);
  });
  $("editor").querySelectorAll(".rowResizeHandle").forEach((handle) => {
    handle.addEventListener("mousedown", startRowResize);
  });
}

function startColumnResize(event) {
  event.preventDefault();
  event.stopPropagation();
  const columnIndex = event.currentTarget.dataset.columnIndex;
  const cell = event.currentTarget.closest("th");
  const startX = event.clientX;
  const startWidth = cell.getBoundingClientRect().width;
  document.body.classList.add("resizingTable");
  const move = (moveEvent) => setColumnWidth(columnIndex, startWidth + moveEvent.clientX - startX);
  const stop = () => {
    document.body.classList.remove("resizingTable");
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", stop);
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", stop);
}

function startRowResize(event) {
  event.preventDefault();
  event.stopPropagation();
  const rowIndex = event.currentTarget.dataset.rowIndex;
  const cell = event.currentTarget.closest("td");
  const startY = event.clientY;
  const startHeight = cell.getBoundingClientRect().height;
  document.body.classList.add("resizingTable");
  const move = (moveEvent) => setRowHeight(rowIndex, startHeight + moveEvent.clientY - startY);
  const stop = () => {
    document.body.classList.remove("resizingTable");
    document.removeEventListener("mousemove", move);
    document.removeEventListener("mouseup", stop);
  };
  document.addEventListener("mousemove", move);
  document.addEventListener("mouseup", stop);
}

function resetTableSize() {
  delete state.columnWidthsByTask[taskLayoutKey()];
  delete state.rowHeightsByTask[taskLayoutKey()];
  persistTableLayout();
  if (state.task) {
    renderTable();
  }
}

function updateActiveRow() {
  $("editor").querySelectorAll("tbody tr").forEach((tr) => {
    tr.classList.toggle("active", Number(tr.dataset.row) === state.selectedRow);
  });
}

function computeMissingClient(task) {
  const missing = {};
  for (let rowIndex = 0; rowIndex < task.rows.length; rowIndex += 1) {
    const row = task.rows[rowIndex];
    const missingHeaders = task.columns
      .filter((column) => column.standard_field)
      .filter((column) => !String(row.values[column.key] ?? "").trim())
      .map((column) => column.header);
    if (missingHeaders.length) {
      missing[String(rowIndex)] = missingHeaders;
    }
  }
  return missing;
}

function escapeHtml(value) {
  return String(value ?? "").replace(/[&<>"']/g, (char) => ({
    "&": "&amp;",
    "<": "&lt;",
    ">": "&gt;",
    '"': "&quot;",
    "'": "&#039;",
  })[char]);
}

function escapeAttribute(value) {
  return escapeHtml(value).replace(/\n/g, " ");
}

$("ratecardForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("ratecardResult").textContent = "正在导入刊例...";
  try {
    const data = await uploadForm(event.currentTarget, "/api/ratecards");
    $("ratecardResult").textContent = `导入成功：版本 #${data.version_id}，达人 ${data.talent_count} 个。`;
    await refreshRatecardStatus();
  } catch (error) {
    $("ratecardResult").textContent = error.message;
  }
});

$("loginForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("loginResult").textContent = "正在登录...";
  try {
    const data = await api("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(authPayloadFromForm(event.currentTarget)),
      noAuth: true,
    });
    setSession(data);
    $("loginResult").textContent = "";
    showAuthenticated();
    await refreshTasks();
    await refreshRatecardStatus();
  } catch (error) {
    $("loginResult").textContent = error.message;
  }
});

$("registerForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("registerResult").textContent = "正在注册...";
  try {
    const data = await api("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(authPayloadFromForm(event.currentTarget)),
      noAuth: true,
    });
    setSession(data);
    $("registerResult").textContent = "";
    showAuthenticated();
    await refreshTasks();
    await refreshRatecardStatus();
  } catch (error) {
    $("registerResult").textContent = error.message;
  }
});

$("logout").addEventListener("click", () => {
  clearSession();
  showSignedOut();
});

$("taskForm").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("taskResult").textContent = "正在创建品牌任务...";
  try {
    const data = await uploadForm(event.currentTarget, "/api/tasks");
    $("taskResult").textContent = `创建成功：任务 #${data.task_id}`;
    await refreshTasks(data.task_id);
  } catch (error) {
    $("taskResult").textContent = error.message;
  }
});

$("refreshTasks").addEventListener("click", () => refreshTasks().catch((error) => setStatus(error.message)));
$("taskSelect").addEventListener("change", (event) => loadTask(event.target.value).catch((error) => setStatus(error.message)));
$("freezeColumns").value = state.frozenColumnCount || "";
$("freezeColumns").addEventListener("input", (event) => {
  const nextCount = Math.max(0, Number(event.target.value) || 0);
  state.frozenColumnCount = nextCount;
  localStorage.removeItem("frozenColumnsSpec");
  localStorage.setItem("frozenColumnCount", String(nextCount));
  if (state.task) {
    renderTable();
  }
});
$("resetTableSize").addEventListener("click", resetTableSize);
$("talentQuery").addEventListener("input", () => {
  state.confirmedTalentMatch = null;
});

$("fillTalent").addEventListener("click", async () => {
  if (!state.task) return;
  const query = $("talentQuery").value.trim();
  if (!query) {
    setStatus("请先输入达人昵称、ID 或主页链接。");
    return;
  }
  setStatus("正在匹配达人并补齐基础信息...");
  try {
    const targetRow = state.selectedRow;
    const data = await api(`/api/tasks/${state.task.id}/fill-from-talent`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_index: targetRow, query }),
    });
    state.task = data.task;
    state.selectedRow = targetRow;
    state.confirmedTalentMatch = { rowIndex: targetRow, query };
    renderTask();
    setStatus(`已匹配：${data.talent.nickname || data.talent.account_id || data.talent.unique_key}。现在可解析二询并填入这行。`);
  } catch (error) {
    setStatus(error.message);
  }
});

$("parseInquiry").addEventListener("click", async () => {
  if (!state.task) return;
  const text = $("inquiryText").value.trim();
  if (!text) {
    setStatus("请先粘贴二询文字。");
    return;
  }
  setStatus("正在解析二询文字...");
  try {
    const query = $("talentQuery").value.trim();
    const confirmedRowIndex = state.confirmedTalentMatch?.query === query ? state.confirmedTalentMatch.rowIndex : null;
    const data = await api(`/api/tasks/${state.task.id}/parse-inquiry`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ row_index: state.selectedRow, text, match_query: query, confirmed_row_index: confirmedRowIndex }),
    });
    state.task = data.task;
    if (Number.isInteger(data.target_row_index)) {
      state.selectedRow = data.target_row_index;
    }
    renderTask();
    const warnings = (data.parsed.warnings || []).join("；");
    if (!data.applied) {
      setStatus("未匹配到唯一达人行，未修改表格。请在上方输入该达人的昵称/小红书号/博主 ID/主页链接后，再点一次解析二询。");
      return;
    }
    const matched = data.match_info?.matched_by?.startsWith("manual_")
      ? `已按你输入的达人信息匹配到第 ${data.target_row_index + 1} 行。`
      : data.match_info?.matched_by === "confirmed_selected_row"
        ? `已填入刚才补齐确认的第 ${data.target_row_index + 1} 行。`
      : `已按二询达人名称匹配到第 ${data.target_row_index + 1} 行。`;
    setStatus(`已解析二询。${matched}${warnings}`);
  } catch (error) {
    setStatus(error.message);
  }
});

$("saveRows").addEventListener("click", async () => {
  if (!state.task) return;
  state.task.missing = computeMissingClient(state.task);
  setStatus("正在保存...");
  try {
    await api(`/api/tasks/${state.task.id}/rows`, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ rows: state.task.rows, missing: state.task.missing }),
    });
    renderTask();
    setStatus("已保存。");
  } catch (error) {
    setStatus(error.message);
  }
});

$("exportTask").addEventListener("click", async () => {
  if (!state.task) return;
  setStatus("正在导出 Excel...");
  try {
    const response = await api(`/api/tasks/${state.task.id}/export`);
    const blob = await response.blob();
    const url = URL.createObjectURL(blob);
    const link = document.createElement("a");
    link.href = url;
    link.download = `品牌表格_已填写_${state.task.id}.xlsx`;
    document.body.appendChild(link);
    link.click();
    link.remove();
    URL.revokeObjectURL(url);
    setStatus("已导出。");
  } catch (error) {
    setStatus(error.message);
  }
});

bootstrap();

