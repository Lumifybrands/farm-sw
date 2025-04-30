document.addEventListener('DOMContentLoaded', () => {
    const loginBtn = document.getElementById('loginBtn');
    const loginFields = document.getElementById('loginFields');
    const formGroups = document.querySelectorAll('.form-group');
    const submitBtn = document.querySelector('.submit-btn');

    // Check if user is already logged in
    fetch('/dashboard')
        .then(response => {
            if (response.redirected) {
                // Not logged in, show login form
                loginBtn.classList.remove('hidden');
            } else {
                // Already logged in, redirect to dashboard
                window.location.href = '/dashboard';
            }
        })
        .catch(() => {
            loginBtn.classList.remove('hidden');
        });

    loginBtn.addEventListener('click', () => {
        loginBtn.classList.add('hidden');
        loginFields.classList.remove('hidden');
        
        // Animate form groups sequentially
        formGroups.forEach((group, index) => {
            setTimeout(() => {
                group.classList.add('visible');
            }, index * 200);
        });

        // Animate submit button
        setTimeout(() => {
            submitBtn.classList.add('visible');
        }, formGroups.length * 200);
    });

    // Handle form submission
    loginFields.addEventListener('submit', async (e) => {
        e.preventDefault();
        const formData = new FormData(loginFields);
        
        try {
            const response = await fetch('/login', {
                method: 'POST',
                headers: {
                    'Content-Type': 'application/json',
                },
                body: JSON.stringify({
                    username: formData.get('username'),
                    password: formData.get('password'),
                    remember: formData.get('remember') === 'on'
                })
            });

            const data = await response.json();
            if (data.success) {
                sessionStorage.setItem('userType', data.user_type);
                window.location.href = '/dashboard';
            } else {
                alert('Invalid credentials. Please try again.');
            }
        } catch (error) {
            console.error('Error:', error);
            alert('An error occurred. Please try again.');
        }
    });
});