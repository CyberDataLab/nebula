document.addEventListener('DOMContentLoaded', function() {
    if (window.location.pathname.includes("api")) {
        document.querySelector('.md-sidebar--primary').style.display = 'block';
    }
});
