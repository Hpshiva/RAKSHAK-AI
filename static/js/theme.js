// ==========================================
// RAKSHAK AI - THEME TOGGLER
// ==========================================

function getTheme() {
    return localStorage.getItem('theme') || 'dark'; // Default to dark
}

function setTheme(theme) {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
    
    // Update toggle icons across the page if they exist
    const icons = document.querySelectorAll('.theme-toggle-btn i');
    icons.forEach(icon => {
        if (theme === 'dark') {
            icon.classList.remove('fa-moon');
            icon.classList.add('fa-sun');
        } else {
            icon.classList.remove('fa-sun');
            icon.classList.add('fa-moon');
        }
    });
}

function toggleTheme() {
    const currentTheme = getTheme();
    const newTheme = currentTheme === 'dark' ? 'light' : 'dark';
    setTheme(newTheme);
}

// Run immediately to prevent FOUC (Flash of Unstyled Content)
(function() {
    const theme = getTheme();
    document.documentElement.setAttribute('data-theme', theme);
    
    // When DOM is ready, sync the icons
    document.addEventListener('DOMContentLoaded', () => {
        setTheme(theme);
    });
})();
