/* PGSM File Editor - CodeMirror integration */

function initEditor(serverId, remotePath) {
    var ext = remotePath.split('.').pop().toLowerCase();

    var modeMap = {
        'json':       { name: 'javascript', json: true },
        'sh':         'shell',
        'bash':       'shell',
        'yml':        'yaml',
        'yaml':       'yaml',
        'xml':        'xml',
        'html':       'xml',
        'htm':        'xml',
        'toml':       'toml',
        'properties': 'properties',
        'conf':       'properties',
        'ini':        'properties',
        'cfg':        'properties',
        'txt':        'text/plain',
        'log':        'text/plain',
        'md':         'text/plain',
    };

    var mode = modeMap[ext] || 'text/plain';
    var modeLabel = typeof mode === 'object' ? 'JSON' : mode;

    var cm = CodeMirror.fromTextArea(document.getElementById('editor-content'), {
        mode: mode,
        theme: 'material-darker',
        lineNumbers: true,
        indentWithTabs: false,
        indentUnit: 4,
        tabSize: 4,
        lineWrapping: false,
        autofocus: true,
        extraKeys: {
            'Ctrl-S': saveFile,
            'Cmd-S':  saveFile,
        },
    });

    cm.setSize('100%', '100%');

    // Status bar elements
    var statusMode  = document.getElementById('status-mode');
    var statusLines = document.getElementById('status-lines');
    var statusPos   = document.getElementById('status-pos');
    var saveStatus  = document.getElementById('save-status');

    statusMode.textContent = modeLabel;
    statusLines.textContent = cm.lineCount() + ' lines';

    cm.on('cursorActivity', function() {
        var cursor = cm.getCursor();
        statusPos.textContent = 'Ln ' + (cursor.line + 1) + ', Col ' + (cursor.ch + 1);
    });

    cm.on('change', function() {
        statusLines.textContent = cm.lineCount() + ' lines';
    });

    function saveFile() {
        saveStatus.textContent = 'Saving...';
        saveStatus.className = 'saving';

        var formData = new FormData();
        formData.append('path', remotePath);
        formData.append('content', cm.getValue());

        fetch('/files/' + serverId + '/save', {
            method: 'POST',
            body: formData,
        })
        .then(function(r) { return r.json(); })
        .then(function(data) {
            if (data.ok) {
                saveStatus.textContent = 'Saved';
                saveStatus.className = 'saved';
                originalContent = cm.getValue();
                setTimeout(function() {
                    saveStatus.textContent = '';
                    saveStatus.className = '';
                }, 3000);
            } else {
                saveStatus.textContent = 'Error: ' + (data.error || 'unknown');
                saveStatus.className = 'error';
            }
        })
        .catch(function() {
            saveStatus.textContent = 'Network error';
            saveStatus.className = 'error';
        });
    }

    document.getElementById('btn-save').addEventListener('click', saveFile);

    // Warn on unsaved changes when navigating away
    var originalContent = cm.getValue();
    window.addEventListener('beforeunload', function(e) {
        if (cm.getValue() !== originalContent) {
            e.preventDefault();
            e.returnValue = '';
        }
    });
}
