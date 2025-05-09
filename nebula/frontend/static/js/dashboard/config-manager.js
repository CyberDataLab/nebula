// Configuration Manager Module
const ConfigManager = {
    init() {
        this.bindEvents();
    },

    bindEvents() {
        document.querySelectorAll('[id^=config-btn]').forEach(button => {
            button.addEventListener('click', () => {
                this.toggleConfigRow(button.dataset.scenarioName);
            });
        });
    },

    async toggleConfigRow(scenarioName) {
        const configRow = document.getElementById(`config-row-${scenarioName}`);
        const configTextElement = document.getElementById(`config-text-${scenarioName}`);

        if (configRow.style.display === 'none') {
            try {
                const response = await fetch(`/platform/dashboard/${scenarioName}/config`);
                const data = await response.json();

                if (data.status === 'success') {
                    configTextElement.value = JSON.stringify(data.config, null, 2);
                } else {
                    configTextElement.value = 'No configuration available.';
                }
            } catch (error) {
                console.error('Error:', error);
                alert('An error occurred while retrieving the configuration.');
                return;
            }
        }
        configRow.style.display = configRow.style.display === 'none' ? '' : 'none';
    }
};

export default ConfigManager; 