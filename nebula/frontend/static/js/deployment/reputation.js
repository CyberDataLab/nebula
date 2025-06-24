// Reputation System Module
const ReputationManager = (function() {
    function initializeReputationSystem() {
        setupReputationSwitch();
        setupWeightingFactor();
        setupWeightValidation();
        setupInitialReputation();
    }

    function setupReputationSwitch() {
        document.getElementById("reputationSwitch").addEventListener("change", function() {
            const reputationMetrics = document.getElementById("reputation-metrics");
            const reputationSettings = document.getElementById("reputation-settings");
            const weightingSettings = document.getElementById("weighting-settings");

            reputationMetrics.style.display = this.checked ? "block" : "none";
            reputationSettings.style.display = this.checked ? "block" : "none";
            weightingSettings.style.display = this.checked ? "block" : "none";
        });
    }

    function setupWeightingFactor() {
        document.getElementById("weighting-factor").addEventListener("change", function() {
            const showWeights = this.value === "static";
            document.querySelectorAll(".weight-input").forEach(input => {
                input.style.display = showWeights ? "inline-block" : "none";
            });
        });
    }

    function setupWeightValidation() {
        document.querySelectorAll(".weight-input").forEach(input => {
            input.addEventListener("input", validateWeights);
        });
    }

    function validateWeights() {
        let totalWeight = 0;
        document.querySelectorAll(".weight-input").forEach(input => {
            const checkbox = input.previousElementSibling.previousElementSibling;
            if (checkbox.checked && input.style.display !== "none" && input.value) {
                totalWeight += parseFloat(input.value);
            }
        });
        document.getElementById("weight-warning").style.display = totalWeight > 1 ? "block" : "none";
    }

    function setupInitialReputation() {
        document.getElementById("initial-reputation").addEventListener("blur", function() {
            const min = parseFloat(this.min);
            const max = parseFloat(this.max);
            const value = parseFloat(this.value);

            if (value < min) {
                this.value = min;
            } else if (value > max) {
                this.value = max;
            }
        });
    }

    function getReputationConfig() {
        return {
            enabled: document.getElementById("reputationSwitch").checked,
            initialReputation: parseFloat(document.getElementById("initial-reputation").value),
            weightingFactor: document.getElementById("weighting-factor").value,
            metrics: {
                model_similarity: {
                    enabled: document.getElementById("model-similarity").checked,
                    weight: parseFloat(document.getElementById("weight-model-similarity").value)
                },
                num_messages: {
                    enabled: document.getElementById("num-messages").checked,
                    weight: parseFloat(document.getElementById("weight-num-messages").value)
                },
                model_arrival_latency: {
                    enabled: document.getElementById("model-arrival-latency").checked,
                    weight: parseFloat(document.getElementById("weight-model-arrival-latency").value)
                },
                fraction_parameters_changed: {
                    enabled: document.getElementById("fraction-parameters-changed").checked,
                    weight: parseFloat(document.getElementById("weight-fraction-parameters-changed").value)
                }
            }
        };
    }

    function setReputationConfig(config) {
        if (!config) return;

        // Set reputation enabled/disabled
        document.getElementById("reputationSwitch").checked = config.enabled;
        document.getElementById("reputation-metrics").style.display = config.enabled ? "block" : "none";
        document.getElementById("reputation-settings").style.display = config.enabled ? "block" : "none";
        document.getElementById("weighting-settings").style.display = config.enabled ? "block" : "none";

        // Set initial reputation
        document.getElementById("initial-reputation").value = config.initialReputation || 0.2;

        // Set weighting factor
        document.getElementById("weighting-factor").value = config.weightingFactor || "dynamic";
        const showWeights = config.weightingFactor === "static";
        document.querySelectorAll(".weight-input").forEach(input => {
            input.style.display = showWeights ? "inline-block" : "none";
        });

        // Set metrics
        if (config.metrics) {
            // Model Similarity
            document.getElementById("model-similarity").checked = config.metrics.modelSimilarity?.enabled || false;
            document.getElementById("weight-model-similarity").value = config.metrics.modelSimilarity?.weight || 0;

            // Number of Messages
            document.getElementById("num-messages").checked = config.metrics.numMessages?.enabled || false;
            document.getElementById("weight-num-messages").value = config.metrics.numMessages?.weight || 0;

            // Model Arrival Latency
            document.getElementById("model-arrival-latency").checked = config.metrics.modelArrivalLatency?.enabled || false;
            document.getElementById("weight-model-arrival-latency").value = config.metrics.modelArrivalLatency?.weight || 0;

            // Fraction Parameters Changed
            document.getElementById("fraction-parameters-changed").checked = config.metrics.fractionParametersChanged?.enabled || false;
            document.getElementById("weight-fraction-parameters-changed").value = config.metrics.fractionParametersChanged?.weight || 0;
        }

        // Validate weights
        validateWeights();
    }

    function resetReputationConfig() {
        // Reset to default values
        document.getElementById("reputationSwitch").checked = false;
        document.getElementById("reputation-metrics").style.display = "none";
        document.getElementById("reputation-settings").style.display = "none";
        document.getElementById("weighting-settings").style.display = "none";
        document.getElementById("initial-reputation").value = "0.2";
        document.getElementById("weighting-factor").value = "dynamic";
        document.getElementById("weight-warning").style.display = "none";

        // Reset metrics
        document.getElementById("model-similarity").checked = false;
        document.getElementById("weight-model-similarity").value = "0";
        document.getElementById("num-messages").checked = false;
        document.getElementById("weight-num-messages").value = "0";
        document.getElementById("model-arrival-latency").checked = false;
        document.getElementById("weight-model-arrival-latency").value = "0";
        document.getElementById("fraction-parameters-changed").checked = false;
        document.getElementById("weight-fraction-parameters-changed").value = "0";

        // Hide weight inputs
        document.querySelectorAll(".weight-input").forEach(input => {
            input.style.display = "none";
        });
    }

    return {
        initializeReputationSystem,
        getReputationConfig,
        setReputationConfig,
        resetReputationConfig
    };
})();

export default ReputationManager;
