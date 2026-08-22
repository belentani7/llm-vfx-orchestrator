(() => {
  const button = document.querySelector('[data-copy-url]');
  const status = document.querySelector('.copy-status');
  document.getElementById('year').textContent = new Date().getFullYear();
  if (!button || !status) return;
  button.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(button.dataset.copyUrl);
      status.textContent = 'Enlace copiado al portapapeles.';
    } catch {
      status.textContent = 'Copia este enlace: ' + button.dataset.copyUrl;
    }
  });
})();
