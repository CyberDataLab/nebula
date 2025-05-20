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
            updateAttackUI(attackType);
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
        const config = {
            type: attackType,
            poisonedNodePercent: parseFloat(document.getElementById("poisoned-node-percent").value),
            round_start_attack: parseInt(document.getElementById("start-attack").value),
            round_stop_attack: parseInt(document.getElementById("stop-attack").value),
            attack_interval: parseInt(document.getElementById("attack-interval").value)
        };

        switch(attackType) {
            case ATTACK_TYPES.LABEL_FLIPPING:
                config.poisoned_percent = parseFloat(document.getElementById("poisoned-sample-percent").value);
                config.targeted = document.getElementById("targeted").checked;
                if(config.targeted) {
                    config.target_label = parseInt(document.getElementById("target_label").value);
                    config.target_changed_label = parseInt(document.getElementById("target_changed_label").value);
                }
                break;

            case ATTACK_TYPES.SAMPLE_POISONING:
                config.poisoned_percent = parseFloat(document.getElementById("poisoned-sample-percent").value);
                config.poisoned_ratio = parseFloat(document.getElementById("poisoned-noise-percent").value);
                config.noise_type = document.getElementById("noise_type").value;
                config.targeted = document.getElementById("targeted").checked;
                if(config.targeted) {
                    config.target_label = parseInt(document.getElementById("target_label").value);
                }
                break;

            case ATTACK_TYPES.MODEL_POISONING:
                config.poisoned_ratio = parseFloat(document.getElementById("poisoned-noise-percent").value);
                config.noise_type = document.getElementById("noise_type").value;
                break;

            case ATTACK_TYPES.SWAPPING_WEIGHTS:
                config.layer_idx = parseInt(document.getElementById("layer_idx").value);
                break;

            case ATTACK_TYPES.DELAYER:
                config.delay = parseInt(document.getElementById("delay").value);
                config.target_percentage = parseInt(document.getElementById("target-percentage").value);
                config.selection_interval = parseInt(document.getElementById("selection-interval").value);
                break;

            case ATTACK_TYPES.FLOODING:
                config.flooding_factor = parseInt(document.getElementById("flooding-factor").value);
                config.target_percentage = parseInt(document.getElementById("target-percentage").value);
                config.selection_interval = parseInt(document.getElementById("selection-interval").value);
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
        document.getElementById("poisoned-node-percent").value = config.poisonedNodePercent || 0;
        document.getElementById("start-attack").value = config.round_start_attack || 1;
        document.getElementById("stop-attack").value = config.round_stop_attack || 10;
        document.getElementById("attack-interval").value = config.attack_interval || 1;

        // Set attack-specific fields
        switch(config.type) {
            case ATTACK_TYPES.LABEL_FLIPPING:
                document.getElementById("poisoned-sample-percent").value = config.poisoned_percent || 0;
                document.getElementById("targeted").checked = config.targeted || false;
                if(config.targeted) {
                    document.getElementById("target_label").value = config.target_label || 4;
                    document.getElementById("target_changed_label").value = config.target_changed_label || 7;
                }
                break;

            case ATTACK_TYPES.SAMPLE_POISONING:
                document.getElementById("poisoned-sample-percent").value = config.poisoned_percent || 0;
                document.getElementById("poisoned-noise-percent").value = config.poisoned_ratio || 0;
                document.getElementById("noise_type").value = config.noise_type || "Salt";
                document.getElementById("targeted").checked = config.targeted || false;
                if(config.targeted) {
                    document.getElementById("target_label").value = config.target_label || 4;
                }
                break;

            case ATTACK_TYPES.MODEL_POISONING:
                document.getElementById("poisoned-noise-percent").value = config.poisoned_ratio || 0;
                document.getElementById("noise_type").value = config.noise_type || "Salt";
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