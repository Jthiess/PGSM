/**
 * PGSM Console - xterm.js + Flask-SocketIO integration
 * Connects to the server's tmux session via SSH → SocketIO bridge.
 */
function initConsole(serverId, isRunning) {
    const term = new Terminal({
        cursorBlink: true,
        rows: 30,
        cols: 200,
        fontFamily: "'Cascadia Code', 'Fira Code', 'Consolas', monospace",
        fontSize: 13,
        theme: {
            background: '#000000',
            foreground: '#dcddde',
            cursor: '#5865f2',
        },
    });

    const fitAddon = new FitAddon.FitAddon();
    term.loadAddon(fitAddon);
    term.open(document.getElementById('terminal-container'));
    fitAddon.fit();

    window.addEventListener('resize', () => fitAddon.fit());

    if (!isRunning) {
        term.write('\r\n[PGSM] Server is not running. Start the server to use the console.\r\n');
        return;
    }

    const socket = io();

    socket.on('connect', function () {
        term.write('\r\n[PGSM] Connecting to server console...\r\n');
        socket.emit('join_console', { server_id: serverId });
    });

    socket.on('disconnect', function () {
        term.write('\r\n[PGSM] Disconnected from console.\r\n');
    });

    socket.on('console_output', function (data) {
        term.write(data.data);
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
