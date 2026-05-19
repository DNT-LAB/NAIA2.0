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
            allowProposedApi: true,
            rightClickSelectsWord: false
        });

        fitAddon = new FitAddon.FitAddon();
        term.loadAddon(fitAddon);
        term.open(document.getElementById("terminal-container"));
        fitAddon.fit();

        // ── 클립보드 유틸 ──

        // Qt 브리지 경유 복사 (QtWebEngine에서 navigator.clipboard 사용 불가)
        function copyText(text) {
            if (!text) return;
            // 1순위: Qt 브리지
            if (bridge && bridge.copyToClipboard) {
                bridge.copyToClipboard(text);
                return;
            }
            // 2순위: execCommand fallback
            var ta = document.createElement("textarea");
            ta.value = text;
            ta.style.cssText = "position:fixed;left:-9999px;top:-9999px;opacity:0";
            document.body.appendChild(ta);
            ta.select();
            try { document.execCommand("copy"); } catch (_) {}
            document.body.removeChild(ta);
        }

        // 선택 텍스트 정리 (개행 → 공백, 중복 공백 제거)
        function getCleanSelection() {
            if (!term.hasSelection()) return "";
            return term.getSelection().replace(/\r?\n/g, " ").replace(/  +/g, " ").trim();
        }

        // ── 커스텀 우클릭 컨텍스트 메뉴 ──

        var ctxMenu = null;

        function removeCtxMenu() {
            if (ctxMenu && ctxMenu.parentNode) {
                ctxMenu.parentNode.removeChild(ctxMenu);
            }
            ctxMenu = null;
        }

        function createCtxMenu(x, y) {
            removeCtxMenu();
            var sel = getCleanSelection();
            var hasSel = sel.length > 0;

            ctxMenu = document.createElement("div");
            ctxMenu.className = "ctx-menu";
            ctxMenu.style.left = x + "px";
            ctxMenu.style.top = y + "px";

            var items = [];

            if (hasSel) {
                items.push({ label: "Copy", action: function () {
                    copyText(sel);
                    term.clearSelection();
                }});
            }

            items.push({ label: "Paste", action: function () {
                if (bridge && bridge.readClipboard) {
                    bridge.readClipboard();
                }
            }});

            if (hasSel) {
                items.push({ type: "separator" });
                items.push({ label: "Send to General", cls: "accent", action: function () {
                    if (bridge && bridge.sendToGeneral) {
                        bridge.sendToGeneral(sel);
                    }
                    term.clearSelection();
                }});
                items.push({ label: "Send & Generate", cls: "accent", action: function () {
                    if (bridge && bridge.sendAndGenerate) {
                        bridge.sendAndGenerate(sel);
                    }
                    term.clearSelection();
                }});
            }

            for (var i = 0; i < items.length; i++) {
                var it = items[i];
                if (it.type === "separator") {
                    var sep = document.createElement("div");
                    sep.className = "ctx-sep";
                    ctxMenu.appendChild(sep);
                    continue;
                }
                var btn = document.createElement("div");
                btn.className = "ctx-item" + (it.cls ? " " + it.cls : "");
                btn.textContent = it.label;
                btn.addEventListener("click", (function (action) {
                    return function () { removeCtxMenu(); action(); };
                })(it.action));
                ctxMenu.appendChild(btn);
            }

            document.body.appendChild(ctxMenu);

            // 화면 밖으로 넘어가면 보정
            var rect = ctxMenu.getBoundingClientRect();
            if (rect.right > window.innerWidth) {
                ctxMenu.style.left = (window.innerWidth - rect.width - 4) + "px";
            }
            if (rect.bottom > window.innerHeight) {
                ctxMenu.style.top = (window.innerHeight - rect.height - 4) + "px";
            }
        }

        // 기본 컨텍스트 메뉴 차단 + 커스텀 메뉴
        document.addEventListener("contextmenu", function (ev) {
            ev.preventDefault();
            createCtxMenu(ev.clientX, ev.clientY);
        });

        // 다른 곳 클릭 시 메뉴 닫기
        document.addEventListener("mousedown", function (ev) {
            if (ctxMenu && !ctxMenu.contains(ev.target)) {
                removeCtxMenu();
            }
        });

        // Ctrl+C / Ctrl+V 클립보드 처리
        term.attachCustomKeyEventHandler(function (ev) {
            if (ev.type !== "keydown" || !ev.ctrlKey || ev.shiftKey || ev.altKey) return true;

            // Ctrl+C: 선택 영역이 있으면 복사 (개행 제거), 없으면 SIGINT 전달
            if (ev.key === "c" || ev.key === "C") {
                if (term.hasSelection()) {
                    var sel = getCleanSelection();
                    copyText(sel);
                    term.clearSelection();
                    return false;
                }
                return true; // 선택 없으면 SIGINT
            }

            // Ctrl+V: Qt 브리지 경유 붙여넣기
            if (ev.key === "v" || ev.key === "V") {
                ev.preventDefault();
                if (bridge && bridge.readClipboard) {
                    bridge.readClipboard();
                }
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

            // Qt 클립보드 읽기 결과 → 터미널에 붙여넣기
            bridge.clipboardResult.connect(function (text) {
                if (text && term) {
                    term.paste(text);
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
