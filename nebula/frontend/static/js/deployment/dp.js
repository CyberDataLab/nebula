// Differential Privacy Module
const DpManager = (function() {
    const DEFAULT_DP_CONFIG = {
        enabled: false,
        noise_multiplier: 1.0,
        max_grad_norm: 1.0
    };

    function initializeDifferentialPrivacy() {
        setupDpSwitch();
        setDpConfig(DEFAULT_DP_CONFIG);
    }

    function setupDpSwitch() {
        const dpSwitch = document.getElementById("dpSwitch");
        if (!dpSwitch) return;

        dpSwitch.addEventListener("change", function() {
            if (this.checked) {
                disableAdversarialTraining();
            }
            toggleDpSettings(this.checked);
        });
    }

    function disableAdversarialTraining() {
        if (window.AdversarialTrainingManager) {
            window.AdversarialTrainingManager.setAdversarialTrainingConfig({enabled: false});
        }

        const adversarialTrainingSwitch = document.getElementById("adversarialTrainingSwitch");
        const adversarialTrainingSettings = document.getElementById("adversarial-training-settings");
        if (adversarialTrainingSwitch) {
            adversarialTrainingSwitch.checked = false;
        }
        if (adversarialTrainingSettings) {
            adversarialTrainingSettings.style.display = "none";
        }
    }

    function toggleDpSettings(enabled) {
        const dpSettings = document.getElementById("dp-settings");
        if (!dpSettings) return;

        dpSettings.style.display = enabled ? "block" : "none";
    }

    function getDpConfig() {
        const noiseMultiplierInput = document.getElementById("dpNoiseMultiplier");
        const noiseMultiplier = parseFloat(noiseMultiplierInput?.value);
        const maxGradNormInput = document.getElementById("dpMaxGradNorm");
        const maxGradNorm = parseFloat(maxGradNormInput?.value);

        return {
            enabled: Boolean(document.getElementById("dpSwitch")?.checked),
            noise_multiplier: Number.isFinite(noiseMultiplier)
                ? noiseMultiplier
                : DEFAULT_DP_CONFIG.noise_multiplier,
            max_grad_norm: Number.isFinite(maxGradNorm)
                ? maxGradNorm
                : DEFAULT_DP_CONFIG.max_grad_norm
        };
    }

    function setDpConfig(config = DEFAULT_DP_CONFIG) {
        const dpConfig = {
            ...DEFAULT_DP_CONFIG,
            ...(config || {})
        };

        const dpSwitch = document.getElementById("dpSwitch");
        if (!dpSwitch) return;

        dpSwitch.checked = Boolean(dpConfig.enabled);
        const noiseMultiplierInput = document.getElementById("dpNoiseMultiplier");
        if (noiseMultiplierInput) {
            noiseMultiplierInput.value = dpConfig.noise_multiplier;
        }
        const maxGradNormInput = document.getElementById("dpMaxGradNorm");
        if (maxGradNormInput) {
            maxGradNormInput.value = dpConfig.max_grad_norm;
        }
        toggleDpSettings(dpSwitch.checked);
    }

    function resetDpConfig() {
        setDpConfig(DEFAULT_DP_CONFIG);
    }

    return {
        initializeDifferentialPrivacy,
        getDpConfig,
        setDpConfig,
        resetDpConfig
    };
})();

export default DpManager;
