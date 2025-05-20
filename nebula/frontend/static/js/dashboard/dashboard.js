import ScenarioActions from './scenario-actions.js';
import NotesManager from './notes-manager.js';
import ConfigManager from './config-manager.js';

// Main Dashboard Module
const Dashboard = {
    init() {
        this.initializeModules();
        // Only show demo message if user is not logged in
        if (typeof window.userLoggedIn === 'boolean' && !window.userLoggedIn) {
            this.checkDemoMode();
        }
    },

    initializeModules() {
        ScenarioActions.init();
        NotesManager.init();
        ConfigManager.init();
    },

    checkDemoMode() {
        showAlert('info', 'Some functionalities are disabled in the demo version.');
    }
};

// Initialize dashboard when DOM is ready
document.addEventListener('DOMContentLoaded', () => {
    Dashboard.init();
});

export default Dashboard; 