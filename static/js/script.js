// Modal functionality
function showLoginModal() {
    const modal = document.getElementById('loginModal');
    modal.style.display = 'block';
}

function closeLoginModal() {
    const modal = document.getElementById('loginModal');
    modal.style.display = 'none';
}

// Close modal when clicking outside
window.onclick = function(event) {
    const modal = document.getElementById('loginModal');
    if (event.target === modal) {
        modal.style.display = 'none';
    }
}

// Login box functionality
function toggleLoginForm() {
    const loginBoxContent = document.getElementById('loginBoxContent');
    const loginToggleBtn = document.querySelector('.login-toggle-btn');
    
    if (loginBoxContent.classList.contains('expanded')) {
        // Collapse
        loginBoxContent.classList.remove('expanded');
        loginToggleBtn.textContent = 'Login';
    } else {
        // Expand
        loginBoxContent.classList.add('expanded');
        loginToggleBtn.textContent = 'Close';
    }
}

// Initialize login box state
document.addEventListener('DOMContentLoaded', function() {
    const loginBoxContent = document.getElementById('loginBoxContent');
    // Only proceed if the element exists
    if (loginBoxContent) {
        // Start with collapsed state
        loginBoxContent.classList.remove('expanded');
    }
});

// // Form submission handling
// document.getElementById('loginForm').addEventListener('submit', function(e) {
//     e.preventDefault();
    
//     const username = document.getElementById('username').value;
//     const password = document.getElementById('password').value;
    
//     // Here you would typically make an API call to your backend
//     console.log('Login attempt:', { username, password });
    
//     // For now, we'll just show an alert
//     alert('Login functionality will be implemented with the backend');
// }); 