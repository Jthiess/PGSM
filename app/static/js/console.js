/**
 * PGSM Console - xterm.js + Flask-SocketIO integration
 * Connects to the server's tmux session via SSH → SocketIO bridge.
 */
function initConsole(serverId, isRunning) {
    // Terminal colours match the PGSM "vCard" palette (see theme.css).
    // window.PGSM_TERM_THEME may override these if set by a host page.
    var termTheme = window.PGSM_TERM_THEME || {};
    const term = new Terminal({
        cursorBlink: true,
        fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
        fontSize: 13,
        scrollback: 5000,
        theme: {
            background: termTheme.bg     || '#161618',
            foreground: termTheme.fg     || '#d6d6d6',
            cursor:     termTheme.cursor || '#9b7bff',
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

    const input = document.getElementById('cmd-input');
    const sendBtn = document.getElementById('cmd-send');

    function setConnected(connected) {
        if (input) {
            input.disabled = !connected;
            input.placeholder = connected
                ? 'Type a command and press Enter…'
                : 'Disconnected — reconnecting…';
        }
        if (sendBtn) sendBtn.disabled = !connected;
    }

    setConnected(false);  // start disabled until the socket connects

    socket.on('connect', function () {
        term.write('\r\n[PGSM] Connecting to server console...\r\n');
        socket.emit('join_console', { server_id: serverId, ...getDimensions() });
        setConnected(true);
    });

    socket.on('disconnect', function () {
        term.write('\r\n[PGSM] Disconnected from console. Attempting to reconnect…\r\n');
        setConnected(false);
    });

    socket.on('connect_error', function () {
        term.write('\r\n[PGSM] Connection error — retrying…\r\n');
        setConnected(false);
    });

    socket.on('console_output', function (data) {
        term.write(data.data);
    });

    // Sync terminal size to server when browser is resized
    window.addEventListener('resize', function () {
        fitAddon.fit();
        socket.emit('console_resize', { server_id: serverId, ...getDimensions() });
    });

    // Send command via input field (input/sendBtn declared above)
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
