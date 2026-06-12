// Feature Squeezing Module
const FeatureSqueezingManager = (function() {
    const DEFAULT_FEATURE_SQUEEZING_CONFIG = {
        enabled: false,
        bit_depth: 4
    };
    const ALLOWED_BIT_DEPTHS = [1, 2, 4, 8, 16, 32, 64];
    const IMAGE_DATASETS = new Set(["MNIST", "FashionMNIST", "EMNIST", "CIFAR10", "CIFAR100"]);

    function initializeFeatureSqueezing() {
        setupFeatureSqueezingSwitch();
        setupDatasetAwareness();
        setFeatureSqueezingConfig(DEFAULT_FEATURE_SQUEEZING_CONFIG);
    }

    function setupFeatureSqueezingSwitch() {
        const featureSqueezingSwitch = document.getElementById("featureSqueezingSwitch");
        if (!featureSqueezingSwitch) return;

        featureSqueezingSwitch.addEventListener("change", function() {
            toggleFeatureSqueezingSettings(this.checked);
        });
    }

    function setupDatasetAwareness() {
        const datasetSelect = document.getElementById("datasetSelect");
        if (!datasetSelect) return;

        datasetSelect.addEventListener("change", updateDatasetAvailability);
        updateDatasetAvailability();
    }

    function toggleFeatureSqueezingSettings(enabled) {
        const featureSqueezingSettings = document.getElementById("feature-squeezing-settings");
        if (!featureSqueezingSettings) return;

        featureSqueezingSettings.style.display = enabled ? "block" : "none";
    }

    function updateDatasetAvailability() {
        const dataset = document.getElementById("datasetSelect")?.value;
        const enabledForDataset = IMAGE_DATASETS.has(dataset);
        const featureSqueezingSwitch = document.getElementById("featureSqueezingSwitch");
        const datasetNote = document.getElementById("feature-squeezing-dataset-note");

        if (datasetNote) {
            datasetNote.style.display = enabledForDataset ? "none" : "block";
        }

        if (!featureSqueezingSwitch) return;
        featureSqueezingSwitch.disabled = !enabledForDataset;
        if (!enabledForDataset) {
            featureSqueezingSwitch.checked = false;
            toggleFeatureSqueezingSettings(false);
        }
    }

    function getFeatureSqueezingConfig() {
        const nInput = document.getElementById("featureSqueezingN");
        const bitDepth = parseInt(nInput?.value, 10);

        return {
            enabled: Boolean(document.getElementById("featureSqueezingSwitch")?.checked),
            bit_depth: normalizeBitDepth(bitDepth)
        };
    }

    function setFeatureSqueezingConfig(config = DEFAULT_FEATURE_SQUEEZING_CONFIG) {
        const featureSqueezingConfig = {
            ...DEFAULT_FEATURE_SQUEEZING_CONFIG,
            ...(config || {})
        };
        const bitDepth = featureSqueezingConfig.bit_depth ?? featureSqueezingConfig.n;

        const featureSqueezingSwitch = document.getElementById("featureSqueezingSwitch");
        if (!featureSqueezingSwitch) return;

        featureSqueezingSwitch.checked = Boolean(featureSqueezingConfig.enabled);
        const nInput = document.getElementById("featureSqueezingN");
        if (nInput) {
            nInput.value = normalizeBitDepth(bitDepth);
        }
        toggleFeatureSqueezingSettings(featureSqueezingSwitch.checked);
        updateDatasetAvailability();
    }

    function normalizeBitDepth(value) {
        const bitDepth = parseInt(value, 10);
        if (ALLOWED_BIT_DEPTHS.includes(bitDepth)) {
            return bitDepth;
        }
        return DEFAULT_FEATURE_SQUEEZING_CONFIG.bit_depth;
    }

    function resetFeatureSqueezingConfig() {
        setFeatureSqueezingConfig(DEFAULT_FEATURE_SQUEEZING_CONFIG);
    }

    return {
        initializeFeatureSqueezing,
        getFeatureSqueezingConfig,
        setFeatureSqueezingConfig,
        resetFeatureSqueezingConfig
    };
})();

export default FeatureSqueezingManager;
