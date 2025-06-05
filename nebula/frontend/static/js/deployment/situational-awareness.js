const SaManager = (function() {
    function initializeSa() {
        setupSaSwitch();
        setupSarTrainingSwitch();
        strictTopologySwitch();
    }

    function setupSaSwitch() {
        document.getElementById("situationalAwarenessSwitch").addEventListener("change", function() {
            const sa_settings = document.getElementById("sa-settings");
            const sa_discovery_settings = document.getElementById("sa-discovery-settings");
            const sa_reasoner_settings = document.getElementById("sa-reasoner-settings");
            const with_mobility = document.getElementById("mobility-btn");
            const without_mobility = document.getElementById("without-mobility-btn");

            sa_settings.style.display = this.checked ? "block" : "none";
            sa_discovery_settings.style.display = this.checked ? "block" : "none";
            sa_reasoner_settings.style.display = this.checked ? "block" : "none";

            if (this.checked){
                with_mobility.checked = true
                without_mobility.checked = false
            } else {
                with_mobility.checked = false
                without_mobility.checked = true
            }
        });
    }

    function setupSarTrainingSwitch(){
        document.getElementById("situationalAwarenessTraining").addEventListener("change", function() {
            const training_policy_title = document.getElementById("training-policy-title");
            const training_policy_container = document.getElementById("training-policy-container");

            training_policy_title.style.display = this.checked ? "block" : "none";
            training_policy_container.style.display = this.checked ? "block" : "none";
        });
    }

    function strictTopologySwitch(){
        document.getElementById("strictTopologySwitch").addEventListener("change", function() {
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
            strict_topology: document.getElementById("strictTopologySwitch").checked,
            sad_candidate_selector: document.getElementById("candidate-selector-select").value,
            sad_model_handler: document.getElementById("model-handler-select").value,
            sar_arbitration_policy: document.getElementById("arbitration-policy-select").value,
            sar_neighbor_policy: document.getElementById("neighbor-policy-select").value,
            sar_training: document.getElementById("situationalAwarenessTraining").checked,
            sar_training_policy: document.getElementById("training-policy-select").value,
        };
    }

    function setSaConfig(config) {
        document.getElementById("situationalAwarenessSwitch").checked = config.with_sa;
        document.getElementById("StrictTopologySwitch").checked = config.strict_topology;
        document.getElementById("candidate-selector-select").value = config.sad_candidate_selector;
        document.getElementById("model-handler-select").value = config.sad_model_handler;
        document.getElementById("arbitration-policy-select").value = config.sar_arbitration_policy;
        document.getElementById("neighbor-policy-select").value = config.sar_neighbor_policy;
        document.getElementById("situationalAwarenessTraining").checked = config.sar_training;
        document.getElementById("training-policy-select").value = config.sar_training_policy;
    }

    function resetSaConfig() {
        document.getElementById("situationalAwarenessSwitch").checked = false;
        document.getElementById("strictTopologySwitch").checked = false;
        document.getElementById("candidate-selector-select").value = "Distance";
        document.getElementById("model-handler-select").value = "std";
        document.getElementById("arbitration-policy-select").value = "sap";
        document.getElementById("neighbor-policy-select").value = "Distance";
        document.getElementById("situationalAwarenessTraining").checked = false;
        document.getElementById("training-policy-select").value = "Broad-Propagation Strategy";
    }

    return {
        initializeSa,
        getSaConfig,
        setSaConfig,
        resetSaConfig
    };
})();

export default SaManager;
