/* Set the selected theme before first paint. An explicit System mode follows OS changes. */
(() => {
  let stored;
  try { stored = localStorage.getItem("jobops-theme"); } catch {}
  const mode = ["auto", "light", "dark"].includes(stored) ? stored : "light";
  const darkOS = window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches;
  document.documentElement.dataset.mode = mode;
  document.documentElement.dataset.theme = mode === "auto" ? (darkOS ? "dark" : "light") : mode;
})();
