const VoiceModule = {
    init() {
        console.log("🎤 Voice Module Initialized");
        this.initAssistant();
    },

    initAssistant() {

        const btn = document.getElementById("voiceBtn");

        if (!btn) return;

        btn.addEventListener("click", () => {

            this.startRecognition();

        });

    },

    processCommand(command) {
        const status = document.getElementById("voiceStatus");
        command = command.toLowerCase().trim();

        if (command.includes("status")) {
            status.innerHTML = `
                <h3 style="color:#00d9ff;">✅ SYSTEM STATUS</h3>

                📷 Cameras : Online<br>

                🤖 Robot : Ready<br>

                🛡 Threat : LOW
            `;
        } else {
            status.innerHTML = `
                ❌ Unknown Command

                <br><br>

                You said:

                <b>${command}</b>
            `;
        }
    },

    startRecognition() {

    console.log("🎤 Voice Started");

    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;

    if (!SpeechRecognition) {

        alert("Speech Recognition is not supported in this browser.");

        return;

    }

    const recognition = new SpeechRecognition();

    recognition.lang = "en-IN";

    recognition.continuous = true;

    recognition.interimResults = true;

    const status = document.getElementById("voiceStatus");

    if(status){
        status.innerHTML = "🎤 Listening...";
    }

    recognition.start();

    recognition.onresult = (event) => {

        const command = event.results[0][0].transcript;

        console.log("🎤 Command :", command);

        if(status){

            status.innerHTML = `
                <strong>You said:</strong><br>
                ${command}
            `;

        }

        this.processCommand(command);

    };

    recognition.onerror = (event) => {

        console.log("Speech Error:", event.error);

        if(status){

            status.innerHTML = `❌ Error : ${event.error}`;

        }

    };

    recognition.onend = () => {

        console.log("Recognition Ended");

    };

    }
};

window.VoiceModule = VoiceModule;