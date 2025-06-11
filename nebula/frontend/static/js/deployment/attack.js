// Attack Configuration Module
const AttackManager = (function() {
    const ATTACK_TYPES = {
        NO_ATTACK: 'No Attack',
        LABEL_FLIPPING: 'Label Flipping',
        SAMPLE_POISONING: 'Sample Poisoning',
        MODEL_POISONING: 'Model Poisoning',
        GLL_NEURON_INVERSION: 'GLL Neuron Inversion',
        SWAPPING_WEIGHTS: 'Swapping Weights',
        DELAYER: 'Delayer',
        FLOODING: 'Flooding'
    };

    function updateAttackUI(attackType) {
        const elements = {
            poisonedNode: {title: document.getElementById("poisoned-node-title"), container: document.getElementById("poisoned-node-percent-container")},
            poisonedSample: {title: document.getElementById("poisoned-sample-title"), container: document.getElementById("poisoned-sample-percent-container")},
            poisonedNoise: {title: document.getElementById("poisoned-noise-title"), container: document.getElementById("poisoned-noise-percent-container")},
            noiseType: {title: document.getElementById("noise-type-title"), container: document.getElementById("noise-type-container")},
            targeted: {title: document.getElementById("targeted-title"), container: document.getElementById("targeted-container")},
            targetLabel: {title: document.getElementById("target_label-title"), container: document.getElementById("target_label-container")},
            targetChangedLabel: {title: document.getElementById("target_changed_label-title"), container: document.getElementById("target_changed_label-container")},
            layerIdx: {title: document.getElementById("layer_idx-title"), container: document.getElementById("layer_idx-container")},
            delay: {title: document.getElementById("delay-title"), container: document.getElementById("delay-container")},
            startAttack: {title: document.getElementById("start-attack-title"), container: document.getElementById("start-attack-container")},
            stopAttack: {title: document.getElementById("stop-attack-title"), container: document.getElementById("stop-attack-container")},
            attackInterval: {title: document.getElementById("attack-interval-title"), container: document.getElementById("attack-interval-container")},
            targetPercentage: {title: document.getElementById("target-percentage-title"), container: document.getElementById("target-percentage-container")},
            selectionInterval: {title: document.getElementById("selection-interval-title"), container: document.getElementById("selection-interval-container")},
            floodingFactor: {title: document.getElementById("flooding-factor-title"), container: document.getElementById("flooding-factor-container")}
        };

        // Hide all elements first
        Object.values(elements).forEach(element => {
            element.title.style.display = "none";
            element.container.style.display = "none";
        });

        // Show relevant elements based on attack type
        switch(attackType) {
            case ATTACK_TYPES.NO_ATTACK:
                break;

            case ATTACK_TYPES.LABEL_FLIPPING:
                showElements(elements, ['poisonedNode', 'poisonedSample', 'targeted', 'startAttack', 'stopAttack', 'attackInterval']);
                if(document.getElementById("targeted").checked) {
                    showElements(elements, ['targetLabel', 'targetChangedLabel']);
                }
                break;

            case ATTACK_TYPES.SAMPLE_POISONING:
                showElements(elements, ['poisonedNode', 'poisonedSample', 'poisonedNoise', 'noiseType', 'targeted', 'startAttack', 'stopAttack', 'attackInterval']);
                break;

            case ATTACK_TYPES.MODEL_POISONING:
                showElements(elements, ['poisonedNode', 'poisonedNoise', 'noiseType', 'startAttack', 'stopAttack', 'attackInterval']);
                break;

            case ATTACK_TYPES.GLL_NEURON_INVERSION:
                showElements(elements, ['poisonedNode', 'startAttack', 'stopAttack', 'attackInterval']);
                break;

            case ATTACK_TYPES.SWAPPING_WEIGHTS:
                showElements(elements, ['poisonedNode', 'layerIdx', 'startAttack', 'stopAttack', 'attackInterval']);
                break;

            case ATTACK_TYPES.DELAYER:
                showElements(elements, ['poisonedNode', 'delay', 'startAttack', 'stopAttack', 'attackInterval', 'targetPercentage', 'selectionInterval']);
                break;

            case ATTACK_TYPES.FLOODING:
                showElements(elements, ['poisonedNode', 'startAttack', 'stopAttack', 'attackInterval', 'targetPercentage', 'selectionInterval', 'floodingFactor']);
                break;
        }
    }

    function showElements(elements, elementKeys) {
        elementKeys.forEach(key => {
            elements[key].title.style.display = "block";
            elements[key].container.style.display = "block";
        });
    }

    function initializeEventListeners() {
        document.getElementById("poisoning-attack-select").addEventListener("change", function() {
            updateAttackUI(this.value);
        });

        document.getElementById("targeted").addEventListener("change", function() {
            const attackType = document.getElementById("poisoning-attack-select").value;
            const elements = {
                targetLabel: {title: document.getElementById("target_label-title"), container: document.getElementById("target_label-container")},
                targetChangedLabel: {title: document.getElementById("target_changed_label-title"), container: document.getElementById("target_changed_label-container")}
            };
            
            if (this.checked && attackType === ATTACK_TYPES.LABEL_FLIPPING) {
                showElements(elements, ['targetLabel', 'targetChangedLabel']);
            } else if (this.checked && attackType === ATTACK_TYPES.SAMPLE_POISONING) {
                showElements(elements, ['targetLabel']);
            } else {
                elements.targetLabel.title.style.display = "none";
                elements.targetLabel.container.style.display = "none";
                elements.targetChangedLabel.title.style.display = "none";
                elements.targetChangedLabel.container.style.display = "none";
            }
        });

        document.getElementById("malicious-nodes-select").addEventListener("change", function() {
            const poisonedNodePercent = document.getElementById("poisoned-node-percent");
            if(this.value === "Manual") {
                poisonedNodePercent.value = 0;
                poisonedNodePercent.disabled = true;
            } else {
                poisonedNodePercent.disabled = false;
            }
        });
    }

    function getAttackConfig() {
        const attackType = document.getElementById("poisoning-attack-select").value;
        
        // Validate numeric inputs
        function validateNumericInput(id, min = 0, max = 100) {
            const value = parseFloat(document.getElementById(id).value);
            if (isNaN(value) || value < min || value > max) {
                throw new Error(`Invalid value for ${id}: must be between ${min} and ${max}`);
            }
            return value;
        }

        // Base config with common parameters
        const config = {
            attacks: attackType, // Send as string instead of array
            poisoned_node_percent: validateNumericInput("poisoned-node-percent"),
            round_start_attack: validateNumericInput("start-attack", 0),
            round_stop_attack: validateNumericInput("stop-attack", 0),
            attack_interval: validateNumericInput("attack-interval", 1)
        };

        // Add attack-specific parameters
        switch(attackType) {
            case ATTACK_TYPES.LABEL_FLIPPING:
                config.poisoned_sample_percent = validateNumericInput("poisoned-sample-percent");
                config.targeted = document.getElementById("targeted").checked;
                if(config.targeted) {
                    config.target_label = validateNumericInput("target_label", 0);
                    config.target_changed_label = validateNumericInput("target_changed_label", 0);
                }
                break;

            case ATTACK_TYPES.SAMPLE_POISONING:
                config.poisoned_sample_percent = validateNumericInput("poisoned-sample-percent");
                config.poisoned_noise_percent = validateNumericInput("poisoned-noise-percent");
                config.noise_type = document.getElementById("noise_type").value;
                config.targeted = document.getElementById("targeted").checked;
                if(config.targeted) {
                    config.target_label = validateNumericInput("target_label", 0);
                }
                break;

            case ATTACK_TYPES.MODEL_POISONING:
                config.poisoned_noise_percent = validateNumericInput("poisoned-noise-percent");
                config.noise_type = document.getElementById("noise_type").value;
                break;

            case ATTACK_TYPES.SWAPPING_WEIGHTS:
                config.layer_idx = validateNumericInput("layer_idx", 0);
                break;

            case ATTACK_TYPES.DELAYER:
                config.delay = validateNumericInput("delay", 0);
                config.target_percentage = validateNumericInput("target-percentage", 0, 100);
                config.selection_interval = validateNumericInput("selection-interval", 1);
                break;

            case ATTACK_TYPES.FLOODING:
                config.flooding_factor = validateNumericInput("flooding-factor", 1);
                config.target_percentage = validateNumericInput("target-percentage", 0, 100);
                config.selection_interval = validateNumericInput("selection-interval", 1);
                break;
        }

        return config;
    }

    function setAttackConfig(config) {
        if (!config) return;

        // Set attack type and update UI
        document.getElementById("poisoning-attack-select").value = config.type;
        updateAttackUI(config.type);

        // Set common fields
        document.getElementById("poisoned-node-percent").value = config.poisoned_node_percent || 0;
        document.getElementById("start-attack").value = config.round_start_attack || 1;
        document.getElementById("stop-attack").value = config.round_stop_attack || 10;
        document.getElementById("attack-interval").value = config.attack_interval || 1;

        // Set attack-specific fields
        switch(config.type) {
            case ATTACK_TYPES.LABEL_FLIPPING:
                document.getElementById("poisoned-sample-percent").value = config.poisoned_sample_percent || 0;
                document.getElementById("targeted").checked = config.targeted || false;
                if(config.targeted) {
                    document.getElementById("target_label").value = config.target_label || 4;
                    document.getElementById("target_changed_label").value = config.target_changed_label || 7;
                }
                break;

            case ATTACK_TYPES.SAMPLE_POISONING:
                document.getElementById("poisoned-sample-percent").value = config.poisoned_sample_percent || 0;
                document.getElementById("poisoned-noise-percent").value = config.poisoned_noise_percent || 0;
                document.getElementById("noise_type").value = config.noise_type || "Gaussian";
                document.getElementById("targeted").checked = config.targeted || false;
                if(config.targeted) {
                    document.getElementById("target_label").value = config.target_label || 4;
                }
                break;

            case ATTACK_TYPES.MODEL_POISONING:
                document.getElementById("poisoned-noise-percent").value = config.poisoned_noise_percent || 0;
                document.getElementById("noise_type").value = config.noise_type || "Gaussian";
                break;

            case ATTACK_TYPES.SWAPPING_WEIGHTS:
                document.getElementById("layer_idx").value = config.layer_idx || 0;
                break;

            case ATTACK_TYPES.DELAYER:
                document.getElementById("delay").value = config.delay || 10;
                document.getElementById("target-percentage").value = config.target_percentage || 100;
                document.getElementById("selection-interval").value = config.selection_interval || 1;
                break;

            case ATTACK_TYPES.FLOODING:
                document.getElementById("flooding-factor").value = config.flooding_factor || 100;
                document.getElementById("target-percentage").value = config.target_percentage || 100;
                document.getElementById("selection-interval").value = config.selection_interval || 1;
                break;
        }
    }

    function resetAttackConfig() {
        document.getElementById("poisoning-attack-select").value = ATTACK_TYPES.NO_ATTACK;
        updateAttackUI(ATTACK_TYPES.NO_ATTACK);
    }

    return {
        ATTACK_TYPES,
        initializeEventListeners,
        updateAttackUI,
        getAttackConfig,
        setAttackConfig,
        resetAttackConfig
    };
})();

export default AttackManager;
