const RobotModule = {

    missionSeconds: 0,

    missionTimer: null,

    missionRunning: false,

    init() {

        console.log("🤖 Robot Module Initialized");

    },

    startMissionTimer() {

        if (this.missionRunning) return;

        this.missionRunning = true;

        this.missionSeconds = 0;

        this.missionTimer = setInterval(() => {

            this.missionSeconds++;

            const minutes = String(Math.floor(this.missionSeconds / 60)).padStart(2, "0");

            const seconds = String(this.missionSeconds % 60).padStart(2, "0");

            const timer = document.getElementById("robotMissionTime");

            if (timer) {

                timer.textContent = `${minutes}:${seconds}`;

            }

        }, 1000);

    },

    stopMissionTimer() {

        clearInterval(this.missionTimer);

        this.missionRunning = false;

    },

    updateMission(dispatch) {

    const mission = document.getElementById("robotMission");

    const missionBar = document.getElementById("missionBar");

    if (mission) {

        mission.textContent =
            dispatch ? "RESPONDING" : "PATROLLING";

    }

    if (missionBar) {

        missionBar.style.width =
            dispatch ? "100%" : "25%";

    }

    if (dispatch) {

        this.startMissionTimer();

    } else {

        this.stopMissionTimer();

    }

},

updateStatus(data) {

    const robotStatus = document.getElementById("robotStatus");
    const robotMode = document.getElementById("robotMode");
    const robotBattery = document.getElementById("robotBattery");
    const robotHealth = document.getElementById("robotHealth");

    if (robotStatus) {
        robotStatus.textContent =
            data.dispatch ? "DISPATCHED" : "STANDBY";
    }

    if (robotMode) {
        robotMode.textContent = data.threat;
    }

    if (robotBattery) {
        robotBattery.textContent =
            data.camera || "No Camera";
    }

    if (robotHealth) {
        robotHealth.textContent = data.people;
    }

}

};

window.RobotModule = RobotModule;