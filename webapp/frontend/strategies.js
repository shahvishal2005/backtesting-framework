const uploadForm = document.getElementById("upload-form");
const uploadButton = document.getElementById("upload-button");
const uploadError = document.getElementById("upload-error");
const uploadSuccess = document.getElementById("upload-success");
const strategyNameInput = document.getElementById("strategy-name");
const projectZipInput = document.getElementById("project-zip");
const fileDropText = document.getElementById("file-drop-text");
const strategiesList = document.getElementById("strategies-list");

projectZipInput.addEventListener("change", () => {
  fileDropText.textContent = projectZipInput.files.length
    ? projectZipInput.files[0].name
    : "Drop ZIP or click to browse";
});

function formatTimestamp(iso) {
  return iso.replace("T", " ").slice(0, 19);
}

function renderStrategies(strategies) {
  if (!strategies.length) {
    strategiesList.innerHTML = '<div class="history-empty">No strategies uploaded yet.</div>';
    return;
  }

  strategiesList.innerHTML = strategies
    .map(
      (s) => `
      <div class="strategy-card">
        <div class="strategy-card-header">
          <span class="strategy-name">${s.name}</span>
          <span class="strategy-version">v${s.version}</span>
        </div>
        <div class="strategy-meta">
          ${s.manifest.entry_point} · ${s.manifest.language} · ${formatTimestamp(s.created_at)} · hash ${s.content_hash}
        </div>
      </div>`
    )
    .join("");
}

async function loadStrategies() {
  const response = await fetch("/api/uploaded-strategies");
  if (!response.ok) throw new Error(`server returned ${response.status}`);
  renderStrategies(await response.json());
}

uploadForm.addEventListener("submit", async (event) => {
  event.preventDefault();
  uploadError.hidden = true;
  uploadSuccess.hidden = true;

  if (!projectZipInput.files.length) {
    uploadError.textContent = "Select a project .zip first.";
    uploadError.hidden = false;
    return;
  }

  const formData = new FormData();
  formData.append("name", strategyNameInput.value);
  formData.append("project_zip", projectZipInput.files[0]);

  uploadButton.disabled = true;
  uploadButton.querySelector("span").textContent = "UPLOADING…";

  try {
    const response = await fetch("/api/uploaded-strategies", { method: "POST", body: formData });
    const payload = await response.json();

    if (!response.ok) {
      uploadError.textContent = payload.detail || "Upload failed.";
      uploadError.hidden = false;
      return;
    }

    uploadSuccess.textContent = `Uploaded ${payload.name} as version ${payload.version}.`;
    uploadSuccess.hidden = false;
    uploadForm.reset();
    fileDropText.textContent = "Drop ZIP or click to browse";
    await loadStrategies();
  } catch (err) {
    uploadError.textContent = `Request failed: ${err.message}`;
    uploadError.hidden = false;
  } finally {
    uploadButton.disabled = false;
    uploadButton.querySelector("span").textContent = "UPLOAD";
  }
});

window.onAuthenticated = async () => {
  await loadStrategies().catch((err) => {
    uploadError.textContent = `Could not load strategies: ${err.message}`;
    uploadError.hidden = false;
  });
};

checkAuth();
