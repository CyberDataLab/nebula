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
        const rep_metrics = [];

        if (document.getElementById("model-similarity").checked)
            rep_metrics.push("model_similarity");
        if (document.getElementById("num-messages").checked)
            rep_metrics.push("num_messages");
        if (document.getElementById("model-arrival-latency").checked)
            rep_metrics.push("model_arrival_latency");
        if (document.getElementById("fraction-parameters-changed").checked)
            rep_metrics.push("fraction_parameters_changed");

        return {
            with_reputation: document.getElementById("reputationSwitch").checked,
            reputation_metrics: rep_metrics,
            initial_reputation: parseFloat(document.getElementById("initial-reputation").value),
            weighting_factor: document.getElementById("weighting-factor").value,
            weight_model_arrival_latency: parseFloat(document.getElementById("weight-model-arrival-latency").value),
            weight_model_similarity: parseFloat(document.getElementById("weight-model-similarity").value),
            weight_num_messages: parseFloat(document.getElementById("weight-num-messages").value),
            weight_fraction_params_changed: parseFloat(document.getElementById("weight-fraction-parameters-changed").value),
        };
    }

    function setReputationConfig(config) {
        if (!config) return;

        const enabled = config.with_reputation ?? config.enabled ?? false;

        // Set reputation switch and visibility
        document.getElementById("reputationSwitch").checked = enabled;
        document.getElementById("reputation-metrics").style.display = enabled ? "block" : "none";
        document.getElementById("reputation-settings").style.display = enabled ? "block" : "none";
        document.getElementById("weighting-settings").style.display = enabled ? "block" : "none";

        // Initial reputation and weighting factor
        document.getElementById("initial-reputation").value = config.initial_reputation ?? config.initialReputation ?? 0.2;
        document.getElementById("weighting-factor").value = config.weighting_factor ?? config.weightingFactor ?? "dynamic";

        const showWeights = (config.weighting_factor ?? config.weightingFactor) === "static";
        document.querySelectorAll(".weight-input").forEach(input => {
            input.style.display = showWeights ? "inline-block" : "none";
        });

        // Metrics (both legacy flat and nested)
        document.getElementById("model-similarity").checked = config.reputation_metrics?.includes("modelSimilarity") ?? config.metrics?.modelSimilarity?.enabled ?? false;
        document.getElementById("weight-model-similarity").value = config.weight_model_similarity ?? config.metrics?.modelSimilarity?.weight ?? 0;

        document.getElementById("num-messages").checked = config.reputation_metrics?.includes("numMessages") ?? config.metrics?.numMessages?.enabled ?? false;
        document.getElementById("weight-num-messages").value = config.weight_num_messages ?? config.metrics?.numMessages?.weight ?? 0;

        document.getElementById("model-arrival-latency").checked = config.reputation_metrics?.includes("modelArrivalLatency") ?? config.metrics?.modelArrivalLatency?.enabled ?? false;
        document.getElementById("weight-model-arrival-latency").value = config.weight_model_arrival_latency ?? config.metrics?.modelArrivalLatency?.weight ?? 0;

        document.getElementById("fraction-parameters-changed").checked = config.reputation_metrics?.includes("fractionParametersChanged") ?? config.metrics?.fractionParametersChanged?.enabled ?? false;
        document.getElementById("weight-fraction-parameters-changed").value = config.weight_fraction_params_changed ?? config.metrics?.fractionParametersChanged?.weight ?? 0;

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
