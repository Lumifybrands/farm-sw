document.addEventListener('DOMContentLoaded', () => {
    const navLinks = document.querySelectorAll('.nav-links a');
    const sections = document.querySelectorAll('.dashboard-section');

    // Navigation handling
    navLinks.forEach(link => {
        link.addEventListener('click', (e) => {
            e.preventDefault();
            
            // Update active nav link
            navLinks.forEach(l => l.classList.remove('active'));
            link.classList.add('active');
            
            // Show corresponding section
            const targetId = link.id.replace('Link', '');
            sections.forEach(section => {
                section.classList.remove('active');
                if (section.id === targetId) {
                    section.classList.add('active');
                }
            });

            // Load section content if needed
            loadSectionContent(targetId);
        });
    });

    // Function to load section content
    async function loadSectionContent(section) {
        try {
            const response = await fetch(`/api/${section}`);
            const data = await response.json();
            
            if (data.success) {
                updateSectionContent(section, data);
            }
        } catch (error) {
            console.error('Error loading section content:', error);
        }
    }

    // Function to update section content
    function updateSectionContent(section, data) {
        switch (section) {
            case 'overview':
                updateOverviewStats(data);
                break;
            case 'inventory':
                // Will be implemented later
                break;
            case 'sales':
                // Will be implemented later
                break;
            case 'reports':
                // Will be implemented later
                break;
            case 'users':
                // Will be implemented later
                break;
        }
    }

    // Function to update overview statistics
    function updateOverviewStats(data) {
        const stats = document.querySelectorAll('.stat-number');
        stats[0].textContent = data.totalBirds || '0';
        stats[1].textContent = data.todayEggs || '0';
        stats[2].textContent = `₹${data.todaySales || '0'}`;
        stats[3].textContent = `${data.feedStock || '0'} kg`;
    }

    // Load initial overview data
    loadSectionContent('overview');
});