/* Apply saved preference or bright reference palette by default before first paint to avoid light/dark flash. */
(() => {
  let stored;
  try { stored = localStorage.getItem("jobops-theme"); } catch {}
  const preferred = stored === "light" || stored === "dark"
    ? stored
    : "light";
  document.documentElement.dataset.theme = preferred;
})();
