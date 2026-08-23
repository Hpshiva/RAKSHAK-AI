function togglePassword(){

const password=document.getElementById("password");
const toggle=document.getElementById("passwordToggle");
const icon=toggle?.querySelector("i");

if(password.type==="password"){

password.type="text";
icon?.classList.replace("fa-eye-slash", "fa-eye");
toggle?.setAttribute("aria-label", "Hide password");
toggle?.setAttribute("aria-pressed", "true");

}else{

password.type="password";
icon?.classList.replace("fa-eye", "fa-eye-slash");
toggle?.setAttribute("aria-label", "Show password");
toggle?.setAttribute("aria-pressed", "false");

}

}

const loginForm = document.getElementById("loginForm");

if (loginForm) {

    loginForm.addEventListener("submit", () => {

        const button = loginForm.querySelector("button");

        button.disabled = true;

        button.innerHTML = `
            <i class="fa-solid fa-spinner fa-spin"></i>
            Authenticating...
        `;

    });

}
