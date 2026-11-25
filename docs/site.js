(() => {
  const yearEl = document.getElementById("year");
  if (yearEl) {
    yearEl.textContent = String(new Date().getFullYear());
  }
  const button = document.querySelector("[data-copy-url]");
  const status = document.querySelector(".copy-status");
  if (!button || !status) return;
  button.addEventListener("click", async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copyUrl);
      status.textContent = "Enlace copiado al portapapeles.";
    } catch {
      status.textContent = "Copia este enlace: " + button.dataset.copyUrl;
    }
  });
})();
