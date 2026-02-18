/**
 * PGSM Theme Switcher
 * Loads the saved theme from localStorage immediately to prevent flash,
 * and provides setTheme() / toggleThemeMenu() for the navbar switcher UI.
 */

(function () {
    'use strict';

    var THEMES = {
        'default':           { label: 'PGSM Dark',  swatch: '#4f8ef7' },
        'light':             { label: 'Light',       swatch: '#0969da' },
        'nord':              { label: 'Nord',        swatch: '#88c0d0' },
        'catppuccin-mocha':  { label: 'Catppuccin',  swatch: '#cba6f7' },
        'gruvbox':           { label: 'Gruvbox',     swatch: '#d79921' }
    };

    var STORAGE_KEY = 'pgsm-theme';

    // Terminal colour palettes per theme (read by console.js)
    var TERM_THEMES = {
        'default':          { bg: '#0d1117', fg: '#c9d1d9', cursor: '#4f8ef7' },
        'light':            { bg: '#1f2328', fg: '#f6f8fa', cursor: '#0969da' },
        'nord':             { bg: '#2e3440', fg: '#d8dee9', cursor: '#88c0d0' },
        'catppuccin-mocha': { bg: '#1e1e2e', fg: '#cdd6f4', cursor: '#cba6f7' },
        'gruvbox':          { bg: '#282828', fg: '#ebdbb2', cursor: '#d79921' }
    };

    /** Return base URL for static files (handles sub-path deployments) */
    function staticBase() {
        var link = document.getElementById('theme-link');
        if (!link) return '/static/';
        // e.g. href = "/static/css/themes/theme-default.css"
        var href = link.getAttribute('href');
        return href.replace(/css\/themes\/theme-[^/]+\.css$/, '');
    }

    /** Apply theme by name without page reload */
    function setTheme(name) {
        if (!THEMES[name]) name = 'default';

        var link = document.getElementById('theme-link');
        if (link) {
            var base = staticBase();
            link.href = base + 'css/themes/theme-' + name + '.css';
        }

        // Expose terminal theme for console.js
        window.PGSM_TERM_THEME = TERM_THEMES[name] || TERM_THEMES['default'];

        // Store preference
        try { localStorage.setItem(STORAGE_KEY, name); } catch (e) { }

        // Update active states on all theme menu items
        document.querySelectorAll('.theme-menu-item[data-theme]').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.theme === name);
        });

        // Close the menu
        var menu = document.getElementById('theme-menu');
        if (menu) menu.classList.remove('open');
    }

    /** Toggle the theme dropdown open/closed */
    function toggleThemeMenu() {
        var menu = document.getElementById('theme-menu');
        if (!menu) return;
        menu.classList.toggle('open');
    }

    /** Close theme menu when clicking outside */
    function handleOutsideClick(e) {
        var switcher = document.querySelector('.theme-switcher');
        if (switcher && !switcher.contains(e.target)) {
            var menu = document.getElementById('theme-menu');
            if (menu) menu.classList.remove('open');
        }
    }

    /** Apply saved theme as early as possible (called immediately) */
    function applyStoredTheme() {
        var saved;
        try { saved = localStorage.getItem(STORAGE_KEY); } catch (e) { }
        var name = (saved && THEMES[saved]) ? saved : 'default';

        // Set terminal theme immediately so console.js can read it
        window.PGSM_TERM_THEME = TERM_THEMES[name] || TERM_THEMES['default'];

        var link = document.getElementById('theme-link');
        if (link) {
            var base = staticBase();
            link.href = base + 'css/themes/theme-' + name + '.css';
        }

        return name;
    }

    // ── Bootstrap ────────────────────────────────────────────────────────────

    // Apply theme as early as possible
    var currentTheme = applyStoredTheme();

    // Once DOM is ready, wire up interactive bits
    function onDOMReady() {
        // Mark active theme item
        document.querySelectorAll('.theme-menu-item[data-theme]').forEach(function (btn) {
            btn.classList.toggle('active', btn.dataset.theme === currentTheme);
        });

        // Close menu on outside click
        document.addEventListener('click', handleOutsideClick);
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', onDOMReady);
    } else {
        onDOMReady();
    }

    // Expose to global scope for inline onclick handlers
    window.setTheme = setTheme;
    window.toggleThemeMenu = toggleThemeMenu;

})();
