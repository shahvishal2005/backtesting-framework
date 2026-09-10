// Shared auth-gate logic for every page (index.html, strategies.html, ...).
// Each page sets window.onAuthenticated = async (email) => {...} for its own
// post-login init (load backtest options, load the strategy list, etc.) before this
// script's checkAuth() call at the bottom runs.

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

async function showAuthenticatedApp(email) {
  userEmailEl.textContent = email;
  userInfo.hidden = false;
  authGate.hidden = true;
  mainLayout.hidden = false;
  if (window.onAuthenticated) await window.onAuthenticated(email);
}

async function checkAuth() {
  const response = await fetch("/api/auth/me");
  if (response.ok) {
    const payload = await response.json();
    await showAuthenticatedApp(payload.email);
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
    await showAuthenticatedApp(payload.email);
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
