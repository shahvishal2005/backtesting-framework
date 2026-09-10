const form = document.getElementById("backtest-form");
const runButton = document.getElementById("run-button");
const errorBox = document.getElementById("error-box");
const emptyState = document.getElementById("empty-state");
const resultsEl = document.getElementById("results");
const metricsGrid = document.getElementById("metrics-grid");
const tradesBody = document.querySelector("#trades-table tbody");
const fileInput = document.getElementById("data-file");
const fileDropText = document.getElementById("file-drop-text");
const strategySelect = document.getElementById("strategy");
const timeframeSelect = document.getElementById("timeframe");
const historyList = document.getElementById("history-list");
const runMeta = document.getElementById("run-meta");

const authGate = document.getElementById("auth-gate");
const mainLayout = document.getElementById("main-layout");
const userInfo = document.getElementById("user-info");
const userEmailEl = document.getElementById("user-email");
const logoutButton = document.getElementById("logout-button");
const authForm = document.getElementById("auth-form");
const authTitle = document.getElementById("auth-title");
const authEmail = document.getElementById("auth-email");
const authPassword = document.getElementById("auth-password");
const authSubmit = document.getElementById("auth-submit");
const authError = document.getElementById("auth-error");
const authToggleText = document.getElementById("auth-toggle-text");
const authToggleLink = document.getElementById("auth-toggle-link");

const marketSelect = document.getElementById("market");
const instrumentSelect = document.getElementById("instrument");
const modeField = document.getElementById("mode-field");
const modeSelect = document.getElementById("mode");
const indianFields = document.getElementById("indian-fields");
const forexFields = document.getElementById("forex-fields");
const cryptoFields = document.getElementById("crypto-fields");
const indianSymbolInput = document.getElementById("indian-symbol");
const cryptoSymbolSelect = document.getElementById("crypto-symbol");

let equityChart = null;
let activeRunId = null;

const startDatePicker = flatpickr("#start-date", {
  dateFormat: "Y-m-d",
  altInput: true,
  altFormat: "M j, Y",
  altInputClass: "text-input alt-date-input",
  onChange: (selectedDates) => {
    if (selectedDates[0]) endDatePicker.set("minDate", selectedDates[0]);
  },
});
const endDatePicker = flatpickr("#end-date", {
  dateFormat: "Y-m-d",
  altInput: true,
  altFormat: "M j, Y",
  altInputClass: "text-input alt-date-input",
  onChange: (selectedDates) => {
    if (selectedDates[0]) startDatePicker.set("maxDate", selectedDates[0]);
  },
});

function updateMarketFields() {
  const market = marketSelect.value;
  indianFields.hidden = market !== "indian";
  forexFields.hidden = market !== "forex";
  cryptoFields.hidden = market !== "crypto";
}

function updateModeField() {
  modeField.hidden = instrumentSelect.value !== "stock";
}

marketSelect.addEventListener("change", updateMarketFields);
instrumentSelect.addEventListener("change", updateModeField);
updateMarketFields();
updateModeField();

function getSelection() {
  const market = marketSelect.value;

  if (market === "indian") {
    const symbol = indianSymbolInput.value.trim().toUpperCase();
    const instrument = instrumentSelect.value;
    const mode = instrument === "stock" ? modeSelect.value : null;
    return { market, symbol, instrument, mode };
  }
  if (market === "forex") {
    return { market, symbol: "XAUUSD", instrument: null, mode: null };
  }
  return { market, symbol: cryptoSymbolSelect.value, instrument: null, mode: null };
}

async function loadOptions() {
  const [strategies, timeframes] = await Promise.all([
    fetch("/api/strategies").then((r) => r.json()),
    fetch("/api/timeframes").then((r) => r.json()),
  ]);

  strategySelect.innerHTML = strategies
    .map((s) => `<option value="${s.id}">${s.name}</option>`)
    .join("");

  timeframeSelect.innerHTML = timeframes
    .map((t) => `<option value="${t}"${t === "daily" ? " selected" : ""}>${t}</option>`)
    .join("");
}

fileInput.addEventListener("change", () => {
  fileDropText.textContent = fileInput.files.length
    ? fileInput.files[0].name
    : "Drop CSV or click to browse";
});

function showError(message) {
  errorBox.textContent = message;
  errorBox.hidden = false;
}

function clearError() {
  errorBox.hidden = true;
  errorBox.textContent = "";
}

function formatNumber(value, digits = 4) {
  if (value === null || value === undefined) return "—";
  return Number(value).toFixed(digits);
}

function signClass(value) {
  if (value === null || value === undefined) return "neutral";
  return value > 0 ? "positive" : value < 0 ? "negative" : "neutral";
}

function renderMetrics(payload) {
  const m = payload.metrics;
  const cards = [
    { label: "Final Equity", value: formatNumber(payload.final_equity, 2), cls: signClass(payload.final_equity - 0) },
    { label: "Total Return", value: `${formatNumber(m.total_return * 100, 3)}%`, cls: signClass(m.total_return) },
    { label: "Sharpe", value: formatNumber(m.sharpe, 3), cls: signClass(m.sharpe) },
    { label: "Max Drawdown", value: `${formatNumber(m.max_drawdown * 100, 3)}%`, cls: "negative" },
    { label: "Win Rate", value: m.win_rate === null ? "—" : `${formatNumber(m.win_rate * 100, 1)}%`, cls: "neutral" },
    { label: "Profit Factor", value: m.profit_factor === null ? "—" : formatNumber(m.profit_factor, 3), cls: "neutral" },
  ];

  metricsGrid.innerHTML = cards
    .map(
      (c) => `
      <div class="metric-card">
        <div class="metric-label">${c.label}</div>
        <div class="metric-value ${c.cls}">${c.value}</div>
      </div>`
    )
    .join("");
}

function renderTrades(trades) {
  tradesBody.innerHTML = trades
    .map(
      (t) => `
      <tr>
        <td>${t.timestamp.replace("T", " ")}</td>
        <td class="action-${t.action.toLowerCase()}">${t.action}</td>
        <td>${t.quantity}</td>
        <td>${formatNumber(t.price, 5)}</td>
        <td>${t.tag ?? "—"}</td>
      </tr>`
    )
    .join("");
}

function renderChart(equityCurve) {
  const ctx = document.getElementById("equity-chart");
  const labels = equityCurve.map((p) => p.timestamp.slice(0, 10));
  const values = equityCurve.map((p) => p.equity);

  if (equityChart) equityChart.destroy();

  equityChart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [
        {
          data: values,
          borderColor: "#d9b556",
          backgroundColor: "rgba(217, 181, 86, 0.12)",
          borderWidth: 2,
          pointRadius: 0,
          tension: 0.15,
          fill: true,
        },
      ],
    },
    options: {
      responsive: true,
      plugins: { legend: { display: false } },
      scales: {
        x: {
          ticks: { color: "#5e594d", maxTicksLimit: 8, font: { family: "JetBrains Mono", size: 10 } },
          grid: { color: "rgba(212, 175, 55, 0.06)" },
        },
        y: {
          ticks: { color: "#5e594d", font: { family: "JetBrains Mono", size: 10 } },
          grid: { color: "rgba(212, 175, 55, 0.06)" },
        },
      },
    },
  });
}

function renderRunMeta(payload) {
  const curve = payload.equity_curve;
  if (!curve.length) {
    runMeta.textContent = "";
    return;
  }
  const start = curve[0].timestamp.slice(0, 10);
  const end = curve[curve.length - 1].timestamp.slice(0, 10);
  runMeta.textContent = `${start} → ${end} · ${curve.length} bars`;
}

function renderResult(payload) {
  emptyState.hidden = true;
  resultsEl.hidden = false;
  renderRunMeta(payload);
  // each render step runs independently — a chart failure (e.g. the CDN script
  // didn't load) shouldn't blank out the metrics/trades that already succeeded
  renderMetrics(payload);
  try {
    renderChart(payload.equity_curve);
  } catch (err) {
    console.error("chart render failed:", err);
  }
  renderTrades(payload.trades);
}

function formatTimestamp(iso) {
  return iso.replace("T", " ").slice(0, 19);
}

const MARKET_LABELS = { indian: "Indian", forex: "Forex", crypto: "Crypto" };

function renderHistory(runs) {
  if (!runs.length) {
    historyList.innerHTML = '<div class="history-empty">No runs yet.</div>';
    return;
  }

  historyList.innerHTML = runs
    .map(
      (run) => `
      <div class="history-row${run.id === activeRunId ? " active" : ""}" data-run-id="${run.id}">
        <div class="history-main">
          <div class="history-symbol">${run.symbol} · ${run.strategy_name}</div>
          <div class="history-meta">${MARKET_LABELS[run.market] ?? "—"} · ${formatTimestamp(run.created_at)} · data ${run.data_version}</div>
        </div>
        <div class="history-equity">${formatNumber(run.final_equity, 2)}</div>
      </div>`
    )
    .join("");
}

async function loadHistory() {
  const runs = await fetch("/api/runs").then((r) => r.json());
  renderHistory(runs);
}

historyList.addEventListener("click", async (event) => {
  const row = event.target.closest(".history-row");
  if (!row) return;

  const runId = Number(row.dataset.runId);
  clearError();
  try {
    const response = await fetch(`/api/runs/${runId}`);
    const payload = await response.json();
    if (!response.ok) {
      showError(payload.detail || "Could not load that run.");
      return;
    }
    activeRunId = runId;
    renderResult(payload);
    [...historyList.children].forEach((el) => el.classList.toggle("active", Number(el.dataset.runId) === runId));
  } catch (err) {
    showError(`Request failed: ${err.message}`);
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  clearError();

  if (!fileInput.files.length) {
    showError("Select a data file first.");
    return;
  }

  const selection = getSelection();
  if (!selection.symbol) {
    showError("Enter a symbol.");
    return;
  }

  const startDate = document.getElementById("start-date").value;
  const endDate = document.getElementById("end-date").value;
  if (startDate && endDate && startDate > endDate) {
    showError("Start Date must be on or before End Date.");
    return;
  }

  const formData = new FormData();
  formData.append("data_file", fileInput.files[0]);
  formData.append("symbol", selection.symbol);
  formData.append("market", selection.market);
  if (selection.instrument) formData.append("instrument", selection.instrument);
  if (selection.mode) formData.append("mode", selection.mode);
  formData.append("strategy", strategySelect.value);
  formData.append("initial_cash", document.getElementById("initial-cash").value);
  formData.append("timeframe", timeframeSelect.value);
  if (startDate) formData.append("start_date", startDate);
  if (endDate) formData.append("end_date", endDate);

  runButton.disabled = true;
  runButton.querySelector("span").textContent = "RUNNING…";

  try {
    const response = await fetch("/api/backtest", { method: "POST", body: formData });
    const payload = await response.json();

    if (!response.ok) {
      showError(payload.detail || "Backtest failed.");
      return;
    }

    activeRunId = payload.run_id;
    renderResult(payload);
    await loadHistory();
  } catch (err) {
    showError(`Request failed: ${err.message}`);
  } finally {
    runButton.disabled = false;
    runButton.querySelector("span").textContent = "RUN BACKTEST";
  }
});

// --- auth -----------------------------------------------------------------------

let authMode = "login"; // or "register"

function setAuthMode(mode) {
  authMode = mode;
  authError.hidden = true;
  if (mode === "login") {
    authTitle.textContent = "Sign In";
    authSubmit.innerHTML = "<span>SIGN IN</span>";
    authToggleText.textContent = "Need an account?";
    authToggleLink.textContent = "Register";
  } else {
    authTitle.textContent = "Create Account";
    authSubmit.innerHTML = "<span>CREATE ACCOUNT</span>";
    authToggleText.textContent = "Already have an account?";
    authToggleLink.textContent = "Sign in";
  }
}

authToggleLink.addEventListener("click", (event) => {
  event.preventDefault();
  setAuthMode(authMode === "login" ? "register" : "login");
});

async function initApp(email) {
  userEmailEl.textContent = email;
  userInfo.hidden = false;
  authGate.hidden = true;
  mainLayout.hidden = false;
  await Promise.all([
    loadOptions().catch((err) => showError(`Could not load options: ${err.message}`)),
    loadHistory().catch((err) => showError(`Could not load run history: ${err.message}`)),
  ]);
}

async function checkAuth() {
  const response = await fetch("/api/auth/me");
  if (response.ok) {
    const payload = await response.json();
    await initApp(payload.email);
  } else {
    authGate.hidden = false;
    mainLayout.hidden = true;
    userInfo.hidden = true;
  }
}

authForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  authError.hidden = true;

  const endpoint = authMode === "login" ? "/api/auth/login" : "/api/auth/register";
  try {
    const response = await fetch(endpoint, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ email: authEmail.value, password: authPassword.value }),
    });
    const payload = await response.json();
    if (!response.ok) {
      authError.textContent = payload.detail || "Something went wrong.";
      authError.hidden = false;
      return;
    }
    authForm.reset();
    await initApp(payload.email);
  } catch (err) {
    authError.textContent = `Request failed: ${err.message}`;
    authError.hidden = false;
  }
});

logoutButton.addEventListener("click", async () => {
  await fetch("/api/auth/logout", { method: "POST" });
  location.reload();
});

setAuthMode("login");
checkAuth();
