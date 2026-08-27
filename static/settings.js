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
  const sidebarToggle = document.getElementById("sidebarToggle");
  const sidebar = document.getElementById("appSidebar");
  const backdrop = document.getElementById("sidebarBackdrop");

  if (sidebarToggle && sidebar && backdrop) {
    sidebarToggle.addEventListener("click", () => {
      sidebar.classList.toggle("open");
      backdrop.classList.toggle("active");
    });

    backdrop.addEventListener("click", () => {
      sidebar.classList.remove("open");
      backdrop.classList.remove("active");
    });
  }
});
