// Копирует текст предложения и открывает диалог. Отправляет человек сам.
document.addEventListener("click", async (event) => {
  const copyBtn = event.target.closest("[data-copy]");
  if (copyBtn) {
    const field = document.querySelector(copyBtn.dataset.copy);
    try {
      await navigator.clipboard.writeText(field.value);
      copyBtn.textContent = "Скопировано — вставьте в диалог";
    } catch {
      field.select();
      copyBtn.textContent = "Выделено — нажмите Ctrl+C";
    }
    if (copyBtn.dataset.open) window.open(copyBtn.dataset.open, "_blank", "noopener");
    return;
  }
  const confirmBtn = event.target.closest("[data-confirm]");
  if (confirmBtn && !window.confirm(confirmBtn.dataset.confirm)) event.preventDefault();
});
