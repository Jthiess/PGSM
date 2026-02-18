/**
 * PGSM Console - xterm.js + Flask-SocketIO integration
 * Connects to the server's tmux session via SSH → SocketIO bridge.
 */
function initConsole(serverId, isRunning) {
    // Use terminal colours from the active PGSM theme (set by theme.js), with fallbacks
    var termTheme = window.PGSM_TERM_THEME || {};
    const term = new Terminal({
        cursorBlink: true,
        fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
        fontSize: 13,
        scrollback: 5000,
        theme: {
            background: termTheme.bg     || '#0d1117',
            foreground: termTheme.fg     || '#c9d1d9',
            cursor:     termTheme.cursor || '#4f8ef7',
        },
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal-container'));
    fitAddon.fit();

    if (!isRunning) {
        term.write('\r\n[PGSM] Server is not running. Start the server to use the console.\r\n');
        return;
    }

    const socket = io();

    // Get dimensions after fit so we can tell the server the exact pty size
    function getDimensions() {
        return { cols: term.cols, rows: term.rows };
    }

    socket.on('connect', function () {
        term.write('\r\n[PGSM] Connecting to server console...\r\n');
        socket.emit('join_console', { server_id: serverId, ...getDimensions() });
    });

    socket.on('disconnect', function () {
        term.write('\r\n[PGSM] Disconnected from console.\r\n');
    });

    socket.on('console_output', function (data) {
        term.write(data.data);
    });

    // Sync terminal size to server when browser is resized
    window.addEventListener('resize', function () {
        fitAddon.fit();
        socket.emit('console_resize', { server_id: serverId, ...getDimensions() });
    });

    // Send command via input field
    const input = document.getElementById('cmd-input');
    const sendBtn = document.getElementById('cmd-send');

    function sendCommand() {
        const cmd = input.value.trim();
        if (!cmd) return;
        socket.emit('console_input', { server_id: serverId, command: cmd });
        input.value = '';
    }

    input.addEventListener('keydown', function (e) {
        if (e.key === 'Enter') sendCommand();
    });

    sendBtn.addEventListener('click', sendCommand);

    // Clean up when leaving page
    window.addEventListener('beforeunload', function () {
        socket.emit('leave_console', { server_id: serverId });
    });
}
