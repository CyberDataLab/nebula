// Adversarial Training Module
const AdversarialTrainingManager = (function() {
    const DEFAULT_ADVERSARIAL_TRAINING_CONFIG = {
        enabled: false,
        domain: "image",
        attack: "fgsm",
        epsilon: 0.03,
        alpha: null,
        steps: 1,
        mode: "mixed",
        apply_probability: 0.3,
        log_adversarial_metrics: true,
        candidate_selection: "none",
        target_loss_increase: null,
        max_loss_increase: null,
        target_margin: 0,
        max_margin: 0.5
    };

    const IMAGE_DATASETS = new Set(["MNIST", "FashionMNIST", "EMNIST", "CIFAR10", "CIFAR100"]);
    const TABULAR_ADVERSARIAL_DATASETS = new Set(["AdultCensus", "BreastCancer", "Covtype", "KDDCUP99"]);
    const IMAGE_ATTACK_OPTIONS = [
        {value: "fgsm", label: "FGSM"},
        {value: "pgd", label: "PGD"}
    ];
    const TABULAR_ATTACK_OPTIONS = [
        {value: "constrained_pgd", label: "Constrained PGD"}
    ];

    function initializeAdversarialTraining() {
        setupAdversarialTrainingSwitch();
        setupAttackSelector();
        setupCandidateSelectionSelector();
        setupDatasetAwareness();
        setAdversarialTrainingConfig(DEFAULT_ADVERSARIAL_TRAINING_CONFIG);
    }

    function setupAdversarialTrainingSwitch() {
        const adversarialTrainingSwitch = document.getElementById("adversarialTrainingSwitch");
        if (!adversarialTrainingSwitch) return;

        adversarialTrainingSwitch.addEventListener("change", function() {
            if (this.checked && window.DpManager) {
                window.DpManager.setDpConfig({enabled: false});
            }
            toggleAdversarialTrainingSettings(this.checked);
        });
    }

    function setupAttackSelector() {
        const attackSelect = document.getElementById("adversarialTrainingAttack");
        if (!attackSelect) return;

        attackSelect.addEventListener("change", function() {
            toggleAttackSettings(this.value);
        });
    }

    function setupCandidateSelectionSelector() {
        const candidateSelectionSelect = document.getElementById("adversarialTrainingCandidateSelection");
        if (!candidateSelectionSelect) return;

        candidateSelectionSelect.addEventListener("change", function() {
            toggleCandidateSelectionSettings(this.value);
        });
    }

    function setupDatasetAwareness() {
        const datasetSelect = document.getElementById("datasetSelect");
        if (!datasetSelect) return;

        datasetSelect.addEventListener("change", updateDatasetAvailability);
        updateDatasetAvailability();
    }

    function toggleAdversarialTrainingSettings(enabled) {
        const settings = document.getElementById("adversarial-training-settings");
        if (!settings) return;

        settings.style.display = enabled ? "block" : "none";
        toggleAttackSettings(document.getElementById("adversarialTrainingAttack")?.value || "fgsm");
    }

    function toggleAttackSettings(attack) {
        const pgdSettings = document.getElementById("adversarial-training-pgd-settings");
        const stepsTitle = document.getElementById("adversarialTrainingStepsTitle");
        const candidateSelectionSettings = document.getElementById("adversarial-training-candidate-selection-settings");
        const lossWindowSettings = document.getElementById("adversarial-training-loss-window-settings");
        const marginWindowSettings = document.getElementById("adversarial-training-margin-window-settings");
        const domain = document.getElementById("adversarialTrainingDomain")?.value || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.domain;
        if (!pgdSettings) return;

        pgdSettings.style.display = ["pgd", "constrained_pgd"].includes(attack) ? "block" : "none";
        if (candidateSelectionSettings) {
            candidateSelectionSettings.style.display = domain === "tabular" ? "block" : "none";
        }
        if (stepsTitle) {
            stepsTitle.textContent = domain === "tabular" ? "Constrained PGD steps" : "PGD steps";
        }
        if (domain !== "tabular") {
            if (lossWindowSettings) lossWindowSettings.style.display = "none";
            if (marginWindowSettings) marginWindowSettings.style.display = "none";
            return;
        }
        toggleCandidateSelectionSettings(
            document.getElementById("adversarialTrainingCandidateSelection")?.value
                || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.candidate_selection
        );
    }

    function toggleCandidateSelectionSettings(candidateSelection) {
        const lossWindowSettings = document.getElementById("adversarial-training-loss-window-settings");
        const marginWindowSettings = document.getElementById("adversarial-training-margin-window-settings");
        if (lossWindowSettings) {
            lossWindowSettings.style.display = candidateSelection === "loss_window" ? "block" : "none";
        }
        if (marginWindowSettings) {
            marginWindowSettings.style.display = candidateSelection === "margin_window" ? "block" : "none";
        }
    }

    function updateDatasetAvailability() {
        const dataset = document.getElementById("datasetSelect")?.value;
        const domain = getDatasetDomain(dataset);
        const adversarialTrainingSwitch = document.getElementById("adversarialTrainingSwitch");
        const datasetNote = document.getElementById("adversarial-training-dataset-note");
        const domainInput = document.getElementById("adversarialTrainingDomain");
        const settings = document.getElementById("adversarial-training-settings");

        if (datasetNote) {
            datasetNote.style.display = domain === "unsupported" ? "block" : "none";
            datasetNote.textContent = "Adversarial Training for tabular datasets currently supports AdultCensus, BreastCancer, Covtype, and KDDCUP99 with constrained PGD.";
        }
        if (domainInput) {
            domainInput.value = domain === "unsupported" ? "tabular" : domain;
        }

        if (!adversarialTrainingSwitch) return;
        adversarialTrainingSwitch.disabled = domain === "unsupported";
        if (domain === "unsupported") {
            adversarialTrainingSwitch.checked = false;
            if (settings) {
                settings.style.display = "none";
            }
            return;
        }

        adversarialTrainingSwitch.disabled = false;
        refreshAttackOptions(domain);
        toggleAdversarialTrainingSettings(adversarialTrainingSwitch.checked);
    }

    function getDatasetDomain(dataset) {
        if (IMAGE_DATASETS.has(dataset)) {
            return "image";
        }
        if (TABULAR_ADVERSARIAL_DATASETS.has(dataset)) {
            return "tabular";
        }
        return "unsupported";
    }

    function refreshAttackOptions(domain, preferredAttack = null) {
        const attackSelect = document.getElementById("adversarialTrainingAttack");
        if (!attackSelect) return;

        // Tabular datasets intentionally expose only constrained PGD; image datasets expose FGSM/PGD.
        const options = domain === "tabular" ? TABULAR_ATTACK_OPTIONS : IMAGE_ATTACK_OPTIONS;
        const currentAttack = preferredAttack || attackSelect.value;
        attackSelect.innerHTML = "";
        options.forEach(({value, label}) => {
            const option = document.createElement("option");
            option.value = value;
            option.textContent = label;
            attackSelect.appendChild(option);
        });

        const validAttack = options.some(option => option.value === currentAttack)
            ? currentAttack
            : options[0].value;
        attackSelect.value = validAttack;
        attackSelect.disabled = domain === "tabular";
        toggleAttackSettings(validAttack);
    }

    function numberValue(id, fallback) {
        const value = parseFloat(document.getElementById(id)?.value);
        return Number.isFinite(value) ? value : fallback;
    }

    function integerValue(id, fallback) {
        const value = parseInt(document.getElementById(id)?.value, 10);
        return Number.isFinite(value) ? value : fallback;
    }

    function optionalNumberValue(id, fallback) {
        const rawValue = document.getElementById(id)?.value;
        if (rawValue === undefined || rawValue === null || rawValue === "") {
            return fallback;
        }
        const value = parseFloat(rawValue);
        return Number.isFinite(value) ? value : fallback;
    }

    function getAdversarialTrainingConfig() {
        const domain = document.getElementById("adversarialTrainingDomain")?.value || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.domain;
        const attack = domain === "tabular"
            ? "constrained_pgd"
            : (document.getElementById("adversarialTrainingAttack")?.value || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.attack);
        const config = {
            enabled: Boolean(document.getElementById("adversarialTrainingSwitch")?.checked),
            domain,
            attack,
            epsilon: numberValue("adversarialTrainingEpsilon", DEFAULT_ADVERSARIAL_TRAINING_CONFIG.epsilon),
            alpha: optionalNumberValue("adversarialTrainingAlpha", DEFAULT_ADVERSARIAL_TRAINING_CONFIG.alpha),
            steps: integerValue("adversarialTrainingSteps", DEFAULT_ADVERSARIAL_TRAINING_CONFIG.steps),
            mode: document.getElementById("adversarialTrainingMode")?.value || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.mode,
            apply_probability: numberValue("adversarialTrainingApplyProbability", DEFAULT_ADVERSARIAL_TRAINING_CONFIG.apply_probability),
            candidate_selection: document.getElementById("adversarialTrainingCandidateSelection")?.value
                || DEFAULT_ADVERSARIAL_TRAINING_CONFIG.candidate_selection,
            target_loss_increase: optionalNumberValue(
                "adversarialTrainingTargetLossIncrease",
                DEFAULT_ADVERSARIAL_TRAINING_CONFIG.target_loss_increase
            ),
            max_loss_increase: optionalNumberValue(
                "adversarialTrainingMaxLossIncrease",
                DEFAULT_ADVERSARIAL_TRAINING_CONFIG.max_loss_increase
            ),
            target_margin: optionalNumberValue(
                "adversarialTrainingTargetMargin",
                DEFAULT_ADVERSARIAL_TRAINING_CONFIG.target_margin
            ),
            max_margin: optionalNumberValue(
                "adversarialTrainingMaxMargin",
                DEFAULT_ADVERSARIAL_TRAINING_CONFIG.max_margin
            ),
            log_adversarial_metrics: true
        };

        if (config.alpha === null || config.attack !== "pgd") {
            delete config.alpha;
        }
        if (config.domain !== "tabular") {
            delete config.candidate_selection;
        }
        if (config.candidate_selection !== "loss_window" || config.target_loss_increase === null) {
            delete config.target_loss_increase;
        }
        if (config.candidate_selection !== "loss_window" || config.max_loss_increase === null) {
            delete config.max_loss_increase;
        }
        if (config.candidate_selection !== "margin_window" || config.target_margin === null) {
            delete config.target_margin;
        }
        if (config.candidate_selection !== "margin_window" || config.max_margin === null) {
            delete config.max_margin;
        }
        return config;
    }

    function setAdversarialTrainingConfig(config = DEFAULT_ADVERSARIAL_TRAINING_CONFIG) {
        const adversarialTrainingConfig = {
            ...DEFAULT_ADVERSARIAL_TRAINING_CONFIG,
            ...(config || {})
        };

        const adversarialTrainingSwitch = document.getElementById("adversarialTrainingSwitch");
        if (!adversarialTrainingSwitch) return;

        adversarialTrainingSwitch.checked = Boolean(adversarialTrainingConfig.enabled);
        setValue("adversarialTrainingEpsilon", adversarialTrainingConfig.epsilon);
        setValue("adversarialTrainingAlpha", adversarialTrainingConfig.alpha ?? "");
        setValue("adversarialTrainingSteps", adversarialTrainingConfig.steps);
        setValue(
            "adversarialTrainingMode",
            ["mixed", "adversarial"].includes(adversarialTrainingConfig.mode)
                ? adversarialTrainingConfig.mode
                : DEFAULT_ADVERSARIAL_TRAINING_CONFIG.mode
        );
        setValue("adversarialTrainingApplyProbability", adversarialTrainingConfig.apply_probability);
        setValue(
            "adversarialTrainingCandidateSelection",
            ["none", "loss_window", "margin_window"].includes(adversarialTrainingConfig.candidate_selection)
                ? adversarialTrainingConfig.candidate_selection
                : DEFAULT_ADVERSARIAL_TRAINING_CONFIG.candidate_selection
        );
        setValue("adversarialTrainingTargetLossIncrease", adversarialTrainingConfig.target_loss_increase ?? "");
        setValue("adversarialTrainingMaxLossIncrease", adversarialTrainingConfig.max_loss_increase ?? "");
        setValue("adversarialTrainingTargetMargin", adversarialTrainingConfig.target_margin ?? 0);
        setValue("adversarialTrainingMaxMargin", adversarialTrainingConfig.max_margin ?? 0.5);

        updateDatasetAvailability();
        const domain = document.getElementById("adversarialTrainingDomain")?.value || adversarialTrainingConfig.domain;
        refreshAttackOptions(domain, adversarialTrainingConfig.attack);
        toggleAdversarialTrainingSettings(adversarialTrainingSwitch.checked);
    }

    function setValue(id, value) {
        const element = document.getElementById(id);
        if (element) {
            element.value = value;
        }
    }

    function resetAdversarialTrainingConfig() {
        setAdversarialTrainingConfig(DEFAULT_ADVERSARIAL_TRAINING_CONFIG);
    }

    function validateConfig() {
        const config = getAdversarialTrainingConfig();
        if (!config.enabled) {
            return null;
        }
        if (config.epsilon < 0) {
            return "[Adversarial Training] Epsilon must be greater than or equal to 0.";
        }
        if (["pgd", "constrained_pgd"].includes(config.attack) && config.steps < 1) {
            return "[Adversarial Training] Search steps must be at least 1.";
        }
        if (!["mixed", "adversarial"].includes(config.mode)) {
            return "[Adversarial Training] Training mode must be Clean + adversarial or Adversarial only.";
        }
        if (config.apply_probability < 0 || config.apply_probability > 1) {
            return "[Adversarial Training] Apply probability must be between 0 and 1.";
        }
        if (
            config.candidate_selection !== undefined
            && !["none", "loss_window", "margin_window"].includes(config.candidate_selection)
        ) {
            return "[Adversarial Training] Candidate selection must be None, Loss window, or Margin window.";
        }
        if (config.target_loss_increase !== undefined && config.target_loss_increase < 0) {
            return "[Adversarial Training] Target loss increase must be greater than or equal to 0.";
        }
        if (config.max_loss_increase !== undefined && config.max_loss_increase < 0) {
            return "[Adversarial Training] Max loss increase must be greater than or equal to 0.";
        }
        if (
            config.target_loss_increase !== undefined
            && config.max_loss_increase !== undefined
            && config.target_loss_increase > config.max_loss_increase
        ) {
            return "[Adversarial Training] Target loss increase must be smaller than or equal to max loss increase.";
        }
        if (
            config.target_margin !== undefined
            && config.max_margin !== undefined
            && config.target_margin > config.max_margin
        ) {
            return "[Adversarial Training] Target margin must be smaller than or equal to max margin.";
        }
        return null;
    }

    return {
        initializeAdversarialTraining,
        getAdversarialTrainingConfig,
        setAdversarialTrainingConfig,
        resetAdversarialTrainingConfig,
        validateConfig
    };
})();

export default AdversarialTrainingManager;
