(function () {
    "use strict";

    var SESSION_ID = "main";
    var term = null;
    var fitAddon = null;
    var bridge = null;
    var initialized = false;

    // xterm.js 터미널 생성
    function createTerminal() {
        term = new Terminal({
            cursorBlink: true,
            cursorStyle: "block",
            fontSize: 18,
            fontFamily: "'Cascadia Code', 'Consolas', 'Courier New', monospace",
            theme: {
                background: "#000000",
                foreground: "#cccccc",
                cursor: "#cccccc",
                selectionBackground: "rgba(128, 128, 255, 0.3)",
                black: "#000000",
                red: "#ff6b6b",
                green: "#51cf66",
                yellow: "#ffd43b",
                blue: "#5c7cfa",
                magenta: "#cc5de8",
                cyan: "#22b8cf",
                white: "#e0e0e0",
                brightBlack: "#666",
                brightRed: "#ff8787",
                brightGreen: "#69db7c",
                brightYellow: "#ffe066",
                brightBlue: "#748ffc",
                brightMagenta: "#da77f2",
                brightCyan: "#3bc9db",
                brightWhite: "#ffffff"
            },
            scrollback: 5000,
            allowProposedApi: true
        });

        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById("terminal-container"));
        fitAddon.fit();

        // Ctrl+C / Ctrl+V 클립보드 처리
        term.attachCustomKeyEventHandler(function (ev) {
            if (ev.type !== "keydown" || !ev.ctrlKey) return true;

            // Ctrl+C: 선택 영역이 있으면 복사, 없으면 SIGINT 전달
            if (ev.key === "c") {
                var sel = term.getSelection();
                if (sel) {
                    navigator.clipboard.writeText(sel);
                    term.clearSelection();
                    return false; // xterm에 전달하지 않음
                }
                return true; // 선택 없으면 SIGINT
            }

            // Ctrl+V: 클립보드에서 붙여넣기
            if (ev.key === "v") {
                navigator.clipboard.readText().then(function (text) {
                    if (text && bridge) {
                        bridge.ptyInput(SESSION_ID, text);
                    }
                });
                return false;
            }

            return true;
        });

        // 키 입력 → Python PTY
        term.onData(function (data) {
            if (bridge) {
                bridge.ptyInput(SESSION_ID, data);
            }
        });

        // 리사이즈 → Python PTY
        term.onResize(function (size) {
            if (bridge) {
                bridge.ptyResize(SESSION_ID, size.cols, size.rows);
            }
        });

        // 컨테이너 리사이즈 감시
        var resizeObserver = new ResizeObserver(function () {
            if (fitAddon && term) {
                try {
                    fitAddon.fit();
                } catch (e) {
                    // 무시
                }
            }
        });
        resizeObserver.observe(document.getElementById("terminal-container"));

        return term;
    }

    // QWebChannel 브리지 연결
    function connectBridge() {
        new QWebChannel(qt.webChannelTransport, function (channel) {
            bridge = channel.objects.bridge;

            // Python PTY 출력 → xterm.js
            bridge.ptyOutput.connect(function (sessionId, data) {
                if (sessionId === SESSION_ID && term) {
                    term.write(data);
                }
            });

            // 프로세스 종료
            bridge.ptyExited.connect(function (sessionId, exitCode) {
                if (sessionId === SESSION_ID && term) {
                    term.write("\r\n\x1b[33m[Process exited with code " + exitCode + "]\x1b[0m\r\n");
                }
            });

            // Python 측에 초기화 완료 알림
            if (!initialized) {
                initialized = true;
                bridge.ptyInput(SESSION_ID, "__TERMINAL_READY__");
            }
        });
    }

    // 초기화
    createTerminal();
    connectBridge();
})();
