const VoiceModule = {
    recognition: null,
    listening: false,
    enabled: false,
    waitingForInteraction: false,
    wakeArmedUntil: 0,
    restartTimer: null,
    feedbackTimer: null,

    init() {
        this.button = document.getElementById("voiceBtn");
        this.status = document.getElementById("voiceStatus");
        if (!this.button) return;

        this.button.addEventListener("click", () => {
            if (this.enabled) this.stopRecognition();
            else {
                this.enabled = true;
                this.startRecognition();
            }
        });

        // Keep voice standby enabled by default. Browsers may require one user
        // interaction before microphone capture, so retry on the first normal
        // click/key press without requiring the mic button specifically.
        this.enabled = true;
        this.startRecognition();

        const activateAfterInteraction = () => {
            if (!this.listening) {
                this.enabled = true;
                this.waitingForInteraction = false;
                this.startRecognition();
            }
        };
        document.addEventListener("pointerdown", activateAfterInteraction, { once: true });
        document.addEventListener("keydown", activateAfterInteraction, { once: true });
    },

    showFeedback(message, isError = false, timeout = 3500) {
        if (!this.status) return;
        window.clearTimeout(this.feedbackTimer);
        this.status.textContent = message;
        this.status.classList.toggle("error", isError);
        this.status.classList.add("show");
        if (timeout) {
            this.feedbackTimer = window.setTimeout(() => {
                this.status.classList.remove("show");
            }, timeout);
        }
    },

    setListening(active) {
        this.listening = active;
        this.button.classList.toggle("is-listening", active);
        this.button.setAttribute("aria-pressed", String(active));
        this.button.setAttribute("aria-label", active ? "Stop voice command" : "Start voice command");
    },

    navigate(path, label) {
        this.showFeedback(`Opening ${label}…`);
        window.setTimeout(() => window.location.assign(path), 350);
    },

    handleWakeCommand(spokenText) {
        const normalized = spokenText.toLowerCase().trim();
        const wakePattern = /(?:hey\s+)?(?:rakshak(?:\s+ai)?|रक्षक)/i;
        const wakeMatch = normalized.match(wakePattern);

        if (wakeMatch) {
            this.wakeArmedUntil = Date.now() + 8000;
            const command = normalized.slice(wakeMatch.index + wakeMatch[0].length)
                .replace(/^[,.:;\s-]+/, "")
                .trim();

            if (command) {
                this.wakeArmedUntil = 0;
                this.processCommand(command);
            } else {
                this.showFeedback("Yes? Say your command within 8 seconds…", false, 8000);
            }
            return;
        }

        if (Date.now() < this.wakeArmedUntil) {
            this.wakeArmedUntil = 0;
            this.processCommand(normalized);
            return;
        }

        // Background speech is intentionally ignored until the wake word is heard.
        this.showFeedback("Standby — say “Hey Rakshak” before a command.", false, 2200);
    },

    processCommand(spokenCommand) {
        const command = spokenCommand.toLowerCase().trim();

        const cameraMatch = command.match(/camera\s*(?:number\s*)?(one|two|three|four|1|2|3|4)/);
        if (cameraMatch && typeof window.switchDashboardCamera === "function") {
            const cameraNumbers = { one: 1, two: 2, three: 3, four: 4 };
            const selectedNumber = cameraNumbers[cameraMatch[1]] || Number(cameraMatch[1]);
            const switcher = document.getElementById("camera-switcher");
            const option = switcher?.options[selectedNumber - 1];
            if (option) {
                switcher.value = option.value;
                window.switchDashboardCamera(option.value);
                this.showFeedback(`Switched to Camera ${selectedNumber}.`);
            } else {
                this.showFeedback(`Camera ${selectedNumber} is not configured.`, true);
            }
            return;
        }

        const routes = [
            { words: ["live camera", "cameras", "camera kholo", "video analysis"], path: "/video_analysis", label: "Live Cameras" },
            { words: ["analytics", "analysis", "analytics kholo"], path: "/analytics", label: "Analytics" },
            { words: ["alerts", "alert", "notifications history", "alert kholo"], path: "/alerts", label: "Alerts" },
            { words: ["settings", "faces", "face settings", "settings kholo"], path: "/faces", label: "Settings" },
            { words: ["about", "about kholo"], path: "/about", label: "About" },
            { words: ["dashboard", "home", "dashboard kholo"], path: "/dashboard", label: "Dashboard" },
        ];

        if (["logout", "log out", "sign out", "logout karo"].some(word => command.includes(word))) {
            this.navigate("/logout", "Login");
            return;
        }

        if (["emergency", "emergency mode", "activate emergency"].some(word => command.includes(word)) && typeof window.triggerEmergency === "function") {
            window.triggerEmergency();
            this.showFeedback("Emergency mode activated.");
            return;
        }

        if (["snapshot", "take photo", "capture photo", "photo lo"].some(word => command.includes(word)) && typeof window.takeSnapshot === "function") {
            window.takeSnapshot();
            this.showFeedback("Snapshot command executed.");
            return;
        }

        if (["report", "generate report", "report kholo"].some(word => command.includes(word)) && typeof window.generateReport === "function") {
            window.generateReport();
            this.showFeedback("Opening security report.");
            return;
        }

        const route = routes.find(item => item.words.some(word => command.includes(word)));
        if (route) {
            this.navigate(route.path, route.label);
            return;
        }

        this.showFeedback(`Command not recognized: “${spokenCommand}”`, true, 5000);
    },

    startRecognition() {
        const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
        if (!SpeechRecognition) {
            this.showFeedback("Voice commands are not supported in this browser. Use Edge or Chrome.", true, 6000);
            return;
        }

        this.recognition = new SpeechRecognition();
        this.recognition.lang = "en-IN";
        this.recognition.continuous = true;
        this.recognition.interimResults = true;
        this.recognition.maxAlternatives = 1;

        this.recognition.onstart = () => {
            this.setListening(true);
            this.showFeedback("Voice standby active — say “Hey Rakshak” followed by a command.", false, 5000);
        };

        this.recognition.onresult = event => {
            const result = event.results[event.results.length - 1];
            const transcript = result[0].transcript.trim();
            if (result.isFinal) this.handleWakeCommand(transcript);
        };

        this.recognition.onerror = event => {
            const messages = {
                "not-allowed": "Allow microphone access once; voice standby will then remain active.",
                "no-speech": "No speech heard. Click the mic and try again.",
                "audio-capture": "No working microphone was found.",
                "network": "Voice recognition network error. Please try again.",
            };
            if (["service-not-allowed", "audio-capture"].includes(event.error)) {
                this.enabled = false;
            }
            if (event.error === "not-allowed") {
                this.waitingForInteraction = true;
            }
            this.showFeedback(messages[event.error] || `Voice error: ${event.error}`, true, 6000);
        };

        this.recognition.onend = () => {
            this.setListening(false);
            if (this.enabled && !this.waitingForInteraction) {
                window.clearTimeout(this.restartTimer);
                this.restartTimer = window.setTimeout(() => this.startRecognition(), 350);
            }
        };

        try {
            this.recognition.start();
        } catch (error) {
            this.setListening(false);
            this.showFeedback("Voice recognition is already active.", true);
        }
    },

    stopRecognition() {
        this.enabled = false;
        this.waitingForInteraction = false;
        this.wakeArmedUntil = 0;
        window.clearTimeout(this.restartTimer);
        if (this.recognition) this.recognition.stop();
        this.setListening(false);
        this.showFeedback("Voice listening stopped.");
    },
};

document.addEventListener("DOMContentLoaded", () => VoiceModule.init());
window.VoiceModule = VoiceModule;
