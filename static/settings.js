document.addEventListener("DOMContentLoaded", () => {
  // ================= SETTINGS =================
  const openBtn = document.getElementById("openSettings");
  const settingsContainer = document.getElementById("settingsContainer");

  if (openBtn && settingsContainer) {
    openBtn.addEventListener("click", () => {
      fetch("/settings/")
        .then((response) => {
          if (!response.ok) {
            throw new Error(`HTTP Error: ${response.status}`);
          }
          return response.text();
        })
        .then((html) => {
          settingsContainer.innerHTML = html;

          const panel = document.getElementById("settingsPanel");
          const closeBtn = document.getElementById("closeSettings");

          if (panel) {
            panel.classList.add("open");
          }

          if (closeBtn) {
            closeBtn.addEventListener("click", () => {
              if (panel) {
                panel.classList.remove("open");
              }

              setTimeout(() => {
                settingsContainer.innerHTML = "";
              }, 350);
            });
          }
        })
        .catch((error) => {
          console.error("Settings Error:", error);
        });
    });
  }

  // ================= SIDEBAR =================
  // Handled centrally in templates/sidebar.html (single toggle binding
  // for all devices). Kept out of here to avoid double-toggle on pages
  // that load both sidebar.html and settings.js.
});
