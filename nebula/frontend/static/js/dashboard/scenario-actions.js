// Scenario Actions Module
const ScenarioActions = {
    init() {
        this.bindEvents();
    },

    bindEvents() {
        $(document).on('click', '#relaunch-btn', this.handleRelaunch.bind(this));
        $(document).on('click', '#remove-btn', this.handleRemove.bind(this));
    },

    handleRelaunch(event) {
        const scenarioName = $(event.currentTarget).data('scenario-name');
        const scenarioTitle = $(event.currentTarget).data('scenario-title');
        
        $('#confirm-modal').modal('show');
        $('#confirm-modal .modal-title').text('Relaunch scenario');
        $('#confirm-modal #confirm-modal-body').html(`Are you sure you want to relaunch the scenario ${scenarioTitle}?`);

        $('#confirm-modal #yes-button').off('click').on('click', () => {
            this.executeRelaunch(scenarioName);
        });
    },

    handleRemove(event) {
        const scenarioName = $(event.currentTarget).data('scenario-name');
        
        $('#confirm-modal').modal('show');
        $('#confirm-modal .modal-title').text('Remove scenario');
        $('#confirm-modal #confirm-modal-body').html(
            `Are you sure you want to remove the scenario ${scenarioName}?<br><br>` +
            `<p class="badge text-bg-danger">Warning: you will remove the scenario from the database</p>`
        );

        $('#confirm-modal #yes-button').off('click').on('click', () => {
            this.executeRemove(scenarioName);
        });
    },

    async executeRelaunch(scenarioName) {
        try {
            const response = await fetch(`/platform/dashboard/${scenarioName}/relaunch`, {
                method: 'GET'
            });

            if (response.redirected) {
                window.location.href = response.url;
            } else {
                $('#confirm-modal').modal('hide');
                $('#confirm-modal').on('hidden.bs.modal', () => {
                    $('#info-modal-body').html('You are not allowed to relaunch a scenario with demo role.');
                    $('#info-modal').modal('show');
                });
            }
        } catch (error) {
            console.error('Error:', error);
        }
    },

    async executeRemove(scenarioName) {
        try {
            const response = await fetch(`/platform/dashboard/${scenarioName}/remove`, {
                method: 'GET'
            });

            if (response.redirected) {
                window.location.href = response.url;
            } else {
                $('#confirm-modal').modal('hide');
                $('#confirm-modal').on('hidden.bs.modal', () => {
                    $('#info-modal-body').html('You are not allowed to remove a scenario with demo role.');
                    $('#info-modal').modal('show');
                });
            }
        } catch (error) {
            console.error('Error:', error);
        }
    }
};

export default ScenarioActions; 