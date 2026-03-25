(function(){
  // Simple theme toggle that stores choice in localStorage and toggles data-theme on <html>
  const KEY = 'site-theme';
  const root = document.documentElement;
  const toggle = document.getElementById('theme-toggle');
  const icon = document.getElementById('theme-icon');

  function setTheme(theme) {
    if (theme === 'light') {
      root.setAttribute('data-theme', 'light');
      icon.innerHTML = '<path d="M6.76 4.84l-1.8-1.79L3.17 4.84 4.97 6.63 6.76 4.84zM1 13h3v-2H1v2zm10 9h2v-3h-2v3zM6.76 19.16l-1.79 1.79 1.41 1.41 1.79-1.79-1.41-1.41zM20.84 7.76l1.79-1.79-1.41-1.41-1.79 1.79 1.41 1.41zM23 11v2h-3v-2h3zM12 4a1 1 0 011 1v2a1 1 0 11-2 0V5a1 1 0 011-1zM17.24 19.16l1.41 1.41 1.79-1.79-1.41-1.41-1.79 1.79z" fill="currentColor"/>';
    } else {
      root.removeAttribute('data-theme');
      icon.innerHTML = '<path d="M21 12.79A9 9 0 1111.21 3 7 7 0 0021 12.79z" fill="currentColor" />';
    }
  }

  function getInitialTheme() {
    const stored = localStorage.getItem(KEY);
    if (stored) return stored;
    // default: prefer dark
    return 'dark';
  }

  function toggleTheme() {
    const current = root.getAttribute('data-theme') === 'light' ? 'light' : 'dark';
    const next = current === 'light' ? 'dark' : 'light';
    setTheme(next);
    localStorage.setItem(KEY, next);
  }

  // Initialize on DOMContentLoaded in case script included in head
  function init() {
    if (!toggle || !icon) return;
    const initial = getInitialTheme();
    setTheme(initial);
    toggle.addEventListener('click', toggleTheme, { passive: true });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
