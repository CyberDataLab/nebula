// Utility Functions Module
const Utils = (function() {
    function showAlert(type, message) {
        // Implementation of alert display
        console.log(`${type}: ${message}`);
    }

    function greaterThan0(input) {
        const value = parseInt(input.value);
        if(value < 1 && !isNaN(value)) {
            input.value = 1;
        }
    }

    function isInRange(input, min, max) {
        const value = parseFloat(input.value);
        if(isNaN(value)) {
            input.value = min;
        } else {
            input.value = Math.min(Math.max(value, min), max);
        }
    }

    function handleProbabilityChange(input) {
        let value = parseFloat(input.value);
        if (isNaN(value)) {
            value = 0.5;
        } else {
            value = Math.min(Math.max(value, 0), 1);
        }
        input.value = value.toFixed(1);
        
        // Trigger topology update if Random is selected
        const topologySelect = document.getElementById('predefined-topology-select');
        if (topologySelect && topologySelect.value === 'Random') {
            window.TopologyManager.generatePredefinedTopology();
        }
    }

    function atLeastOneChecked(checkboxIds) {
        return checkboxIds.some(function(id) {
            const checkbox = document.getElementById(id);
            return checkbox && checkbox.checked;
        });
    }

    function selectALL(checkboxIds, checked) {
        for (let i = 0; i < checkboxIds.length; i++) {
            document.getElementById(checkboxIds[i]).checked = checked;
        }
    }

    return {
        showAlert,
        greaterThan0,
        isInRange,
        atLeastOneChecked,
        selectALL,
        handleProbabilityChange
    };
})();

export default Utils; 