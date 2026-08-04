document.addEventListener("DOMContentLoaded", () => {
    const turnOnCameraBtn = document.getElementById("turnOnCameraBtn");
    const cameraPlaceholder = document.getElementById("cameraPlaceholder");
    const cameraFeed = document.getElementById("cameraFeed");

    if (turnOnCameraBtn) {
        turnOnCameraBtn.addEventListener("click", async () => {
            // Update button state to show loading
            turnOnCameraBtn.innerHTML = '<i class="fa-solid fa-spinner fa-spin"></i> Starting...';
            turnOnCameraBtn.disabled = true;

            try {
                const response = await fetch("/start_camera", {
                    method: "POST"
                });
                
                const data = await response.json();
                if (data.success) {
                    cameraPlaceholder.style.display = "none";
                    
                    // Add a cache-busting timestamp to ensure it reloads
                    const timestamp = new Date().getTime();
                    cameraFeed.src = `/video_feed?t=${timestamp}`;
                    cameraFeed.style.display = "block";
                    
                    if (window.Dashboard && typeof window.Dashboard.addNotification === "function") {
                        window.Dashboard.addNotification("Camera", "Camera started successfully", "success");
                    }
                } else {
                    alert("Failed to turn on camera: " + (data.error || "Unknown error"));
                    // Reset button
                    turnOnCameraBtn.innerHTML = '<i class="fa-solid fa-power-off"></i> Turn On Camera';
                    turnOnCameraBtn.disabled = false;
                }
            } catch (error) {
                console.error("Error turning on camera:", error);
                alert("Error turning on camera. Is the server running?");
                // Reset button
                turnOnCameraBtn.innerHTML = '<i class="fa-solid fa-power-off"></i> Turn On Camera';
                turnOnCameraBtn.disabled = false;
            }
        });
    }
});
