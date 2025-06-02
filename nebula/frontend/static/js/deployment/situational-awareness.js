const SaManager = (function() {
    function initializeSa() {
        setupSaSwitch();
        StrictTopologySwitch();
    }

    function setupSaSwitch() {
        document.getElementById("situationalAwarenessSwitch").addEventListener("change", function() {
            const sa_settings = document.getElementById("sa-settings");
            const sa_discovery_settings = document.getElementById("sa-discovery-settings");
            const sa_reasoner_settings = document.getElementById("sa-reasoner-settings");

            sa_settings.style.display = this.checked ? "block" : "none";
            sa_discovery_settings.style.display = this.checked ? "block" : "none";
            sa_reasoner_settings.style.display = this.checked ? "block" : "none";
        });
    }

    function StrictTopologySwitch(){
        document.getElementById("StrictTopologySwitch").addEventListener("change", function() {
            const candidate_selector = document.getElementById("candidate-selector-select");
            const neighbor_policy = document.getElementById("neighbor-policy-select");

            if (this.checked) {
                candidate_selector.value = document.getElementById("predefined-topology-select").value;
                neighbor_policy.value = document.getElementById("predefined-topology-select").value;
                candidate_selector.disabled = true;
                neighbor_policy.disabled = true;
            } else {
                candidate_selector.value = "Distance";
                neighbor_policy.value = "Distance";
                candidate_selector.disabled = false;
                neighbor_policy.disabled = false;
            }
        });
    }

    function getSaConfig() {
        return {
            with_sa: document.getElementById("situationalAwarenessSwitch").checked,
            strict_topology: document.getElementById("StrictTopologySwitch").checked,
            sad_candidate_selector: document.getElementById("candidate-selector-select").value,
            sad_model_handler: document.getElementById("model-handler-select").value,
            sar_arbitration_policy: document.getElementById("arbitration-policy-select").value,
            sar_neighbor_policy: document.getElementById("neighbor-policy-select").value,
        };
    }

    function setSaConfig(config) {
        document.getElementById("situationalAwarenessSwitch").checked = config.with_sa;
        document.getElementById("StrictTopologySwitch").checked = config.strict_topology;
        document.getElementById("candidate-selector-select").value = config.sad_candidate_selector;
        document.getElementById("model-handler-select").value = config.sad_model_handler;
        document.getElementById("arbitration-policy-select").value = config.sar_arbitration_policy;
        document.getElementById("neighbor-policy-select").value = config.sar_neighbor_policy;
    }

    function resetSaConfig() {
        document.getElementById("situationalAwarenessSwitch").checked = false;
        document.getElementById("StrictTopologySwitch").checked = false;
        document.getElementById("candidate-selector-select").value = "Distance";
        document.getElementById("model-handler-select").value = "std";
        document.getElementById("arbitration-policy-select").value = "sap";
        document.getElementById("neighbor-policy-select").value = "Distance";
    }

    return {
        initializeSa,
        getSaConfig,
        setSaConfig,
        resetSaConfig
    };
})();

export default SaManager;
