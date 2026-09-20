document.addEventListener("DOMContentLoaded", () => {
  // ================= SETTINGS =================
  const openBtn = document.getElementById("openSettings");
  const settingsContainer = document.getElementById("settingsContainer");

  if (openBtn && settingsContainer) {
    openBtn.addEventListener("click", () => {
      showSettingsToast("Opening settings…");
      fetch("/settings/", { cache: "no-store", credentials: "same-origin" })
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP Error: ${response.status}`);
          }
          if (response.redirected && response.url.indexOf("signin") !== -1) {
            // Session expired: the server bounced us to the login page.
            window.location.href = "/signin/";
            return null;
          }
          return response.text();
        })
        .then((html) => {
          if (html === null) {
            return; // Redirect already issued above.
          }
          settingsContainer.innerHTML = html;

          const panel = document.getElementById("settingsPanel");
          if (!panel) {
            // Most likely cause: session expired and the server returned
            // the sign-in page instead of the panel. Never fail silently.
            window.location.href = "/signin/";
            return;
          }
          hideSettingsToast();
          panel.classList.add("open");

          const closeBtn = document.getElementById("closeSettings");
          if (closeBtn) {
            closeBtn.addEventListener("click", () => {
              panel.classList.remove("open");

              setTimeout(() => {
                settingsContainer.innerHTML = "";
              }, 350);
            });
          }
        })
        .catch((error) => {
          console.error("Settings Error:", error);
          showSettingsToast(
            "Couldn't open settings. Check your connection and try again.",
            true
          );
        });
    });
  }

  function showSettingsToast(message, isError) {
    hideSettingsToast();
    const toast = document.createElement("div");
    toast.id = "settingsToast";
    toast.textContent = message;
    toast.style.cssText =
      "position:fixed;left:50%;bottom:24px;transform:translateX(-50%);" +
      "background:" + (isError ? "#dc2626" : "#0f172a") + ";color:#fff;" +
      "padding:0.7rem 1.2rem;border-radius:12px;font-size:0.9rem;" +
      "font-weight:600;z-index:10000;box-shadow:0 10px 25px rgba(0,0,0,.25);" +
      "max-width:calc(100vw - 48px);text-align:center;";
    document.body.appendChild(toast);
    if (!isError) {
      toast.dataset.transient = "1";
    }
  }

  function hideSettingsToast() {
    const existing = document.getElementById("settingsToast");
    if (existing) {
      existing.remove();
    }
  }

  // ================= SIDEBAR =================
  // Handled centrally in templates/sidebar.html (single toggle binding
  // for all devices). Kept out of here to avoid double-toggle on pages
  // that load both sidebar.html and settings.js.
});
