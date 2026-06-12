// Trustworthiness System Module
const TrustworthinessManager = (function() {
    function isTrustworthinessEnabled() {
        const sw = document.getElementById("TrustworthinessSwitch");
        return Boolean(sw?.checked);
    }

    function initializeTrustworthinessSystem() {
        setupTrustworthinessSwitch();
        setupTrustworthinessFederationSwitch();
        setupWeightValidation();
    }

    function isDFL() {
        const ft = document.getElementById("federationArchitecture")?.value || "CFL";
        return (ft === "DFL" || ft === "SDFL");
    }

    function showTrustworthinessWeightsBlock() {
        const cflBlock = document.getElementById("tw-cfl");
        const dflBlock = document.getElementById("tw-dfl");
        if (!cflBlock || !dflBlock) return;

        const use = isDFL();
        cflBlock.style.display = use ? "none" : "block";
        dflBlock.style.display = use ? "block" : "none";
    }

    function setupTrustworthinessSwitch() {
        const sw = document.getElementById("TrustworthinessSwitch");
        if (!sw) return;

        sw.addEventListener("change", function() {
            const trustworthinessOptionsDiv = document.getElementById("trustworthiness-options");
            if (!trustworthinessOptionsDiv) return;

            if (this.checked) {
                trustworthinessOptionsDiv.style.display = "block";
                showTrustworthinessWeightsBlock();
                validateWeights();
            } else {
                trustworthinessOptionsDiv.style.display = "none";
            }
        });
    }

    function setupTrustworthinessFederationSwitch() {
        const fed = document.getElementById("federationArchitecture");
        if (!fed) return;

        fed.addEventListener("change", function() {
            const trustworthinessOptionsDiv = document.getElementById("trustworthiness-options");
            if (trustworthinessOptionsDiv?.style.display === "block") {
                showTrustworthinessWeightsBlock();
                validateWeights();
            }
        });
    }

    function setupWeightValidation() {
        // IDs CFL
        const cflPillarIds = [
            "cfl-robustness-pillar",
            "cfl-privacy-pillar",
            "cfl-fairness-pillar",
            "cfl-explainability-pillar",
            "cfl-accountability-pillar",
            "cfl-architectural-soundness-pillar",
            "cfl-sustainability-pillar"
        ];
        const cflNotionIds = [
            "cfl-robustness-notion-1",
            "cfl-robustness-notion-2",
            "cfl-robustness-notion-3",
            "cfl-privacy-notion-1",
            "cfl-privacy-notion-2",
            "cfl-privacy-notion-3",
            "cfl-fairness-notion-1",
            "cfl-fairness-notion-2",
            "cfl-fairness-notion-3",
            "cfl-fairness-notion-4",
            "cfl-explainability-notion-1",
            "cfl-explainability-notion-2",
            "cfl-accountability-notion-1",
            "cfl-accountability-notion-2",
            "cfl-architectural-soundness-notion-1",
            "cfl-architectural-soundness-notion-2",
            "cfl-architectural-soundness-notion-3",
            "cfl-sustainability-notion-1",
            "cfl-sustainability-notion-2",
            "cfl-sustainability-notion-3"
        ];

        const dflPillarIds = [
            "dfl-robustness-pillar",
            "dfl-privacy-pillar",
            "dfl-fairness-pillar",
            "dfl-explainability-pillar",
            "dfl-accountability-pillar",
            "dfl-architectural-soundness-pillar",
            "dfl-sustainability-pillar"
        ];
        const dflNotionIds = [
            "dfl-robustness-notion-1",
            "dfl-robustness-notion-2",
            "dfl-robustness-notion-3",
            "dfl-privacy-notion-1",
            "dfl-privacy-notion-2",
            "dfl-privacy-notion-3",
            "dfl-fairness-notion-3",
            "dfl-fairness-notion-4",
            "dfl-explainability-notion-1",
            "dfl-explainability-notion-2",
            "dfl-accountability-notion-1",
            "dfl-accountability-notion-2",
            "dfl-architectural-soundness-notion-1",
            "dfl-architectural-soundness-notion-2",
            "dfl-architectural-soundness-notion-3",
            "dfl-sustainability-notion-1",
            "dfl-sustainability-notion-3"
        ];

        cflPillarIds.concat(cflNotionIds, dflPillarIds, dflNotionIds).forEach(id => {
            const input = document.getElementById(id);
            if (input) input.addEventListener("input", validateWeights);
        });
    }

    function validateWeights() {
        if (!isTrustworthinessEnabled()) {
            return null;
        }

        if (isDFL()) {
            return validateWeightsDFL();
        }
        return validateWeightsCFL();
    }

    function getWeightValidationMessage(groupLabel, total) {
        if (total > 100) {
            return `[Trustworthiness] ${groupLabel} weights exceed 100%. Please review the configuration.`;
        }

        if (total < 100) {
            return `[Trustworthiness] ${groupLabel} weights are below 100%. Please review the configuration.`;
        }

        return null;
    }

    function validateWeightsCFL() {
        const robustnessPercent = parseFloat(document.getElementById("cfl-robustness-pillar").value) || 0;
        const privacyPercent = parseFloat(document.getElementById("cfl-privacy-pillar").value) || 0;
        const fairnessPercent = parseFloat(document.getElementById("cfl-fairness-pillar").value) || 0;
        const explainabilityPercent = parseFloat(document.getElementById("cfl-explainability-pillar").value) || 0;
        const accountabilityPercent = parseFloat(document.getElementById("cfl-accountability-pillar").value) || 0;
        const architecturalSoundnessPercent = parseFloat(document.getElementById("cfl-architectural-soundness-pillar").value) || 0;
        const sustainabilityPercent = parseFloat(document.getElementById("cfl-sustainability-pillar").value) || 0;

        const robustnessNotion1 = parseFloat(document.getElementById("cfl-robustness-notion-1").value) || 0;
        const robustnessNotion2 = parseFloat(document.getElementById("cfl-robustness-notion-2").value) || 0;
        const robustnessNotion3 = parseFloat(document.getElementById("cfl-robustness-notion-3").value) || 0;

        const privacyNotion1 = parseFloat(document.getElementById("cfl-privacy-notion-1").value) || 0;
        const privacyNotion2 = parseFloat(document.getElementById("cfl-privacy-notion-2").value) || 0;
        const privacyNotion3 = parseFloat(document.getElementById("cfl-privacy-notion-3").value) || 0;

        const fairnessNotion1 = parseFloat(document.getElementById("cfl-fairness-notion-1").value) || 0;
        const fairnessNotion2 = parseFloat(document.getElementById("cfl-fairness-notion-2").value) || 0;
        const fairnessNotion3 = parseFloat(document.getElementById("cfl-fairness-notion-3").value) || 0;
        const fairnessNotion4 = parseFloat(document.getElementById("cfl-fairness-notion-4").value) || 0;

        const explainabilityNotion1 = parseFloat(document.getElementById("cfl-explainability-notion-1").value) || 0;
        const explainabilityNotion2 = parseFloat(document.getElementById("cfl-explainability-notion-2").value) || 0;

        const architecturalSoundnessNotion1 = parseFloat(document.getElementById("cfl-architectural-soundness-notion-1").value) || 0;
        const architecturalSoundnessNotion2 = parseFloat(document.getElementById("cfl-architectural-soundness-notion-2").value) || 0;
        const architecturalSoundnessNotion3 = parseFloat(document.getElementById("cfl-architectural-soundness-notion-3").value) || 0;

        const sustainabilityNotion1 = parseFloat(document.getElementById("cfl-sustainability-notion-1").value) || 0;
        const sustainabilityNotion2 = parseFloat(document.getElementById("cfl-sustainability-notion-2").value) || 0;
        const sustainabilityNotion3 = parseFloat(document.getElementById("cfl-sustainability-notion-3").value) || 0;

        const accountabilityNotion1 = parseFloat(document.getElementById("cfl-accountability-notion-1").value) || 0;
        const accountabilityNotion2 = parseFloat(document.getElementById("cfl-accountability-notion-2").value) || 0;

        const totalPillar =
            robustnessPercent + privacyPercent + fairnessPercent + explainabilityPercent +
            accountabilityPercent + architecturalSoundnessPercent + sustainabilityPercent;

        const totalRobustnessNotion = robustnessNotion1 + robustnessNotion2 + robustnessNotion3;
        const totalPrivacyNotion = privacyNotion1 + privacyNotion2 + privacyNotion3;
        const totalFairnessNotion = fairnessNotion1 + fairnessNotion2 + fairnessNotion3 + fairnessNotion4;
        const totalExplainabilityNotion = explainabilityNotion1 + explainabilityNotion2;
        const totalArchitecturalSoundnessNotion = architecturalSoundnessNotion1 + architecturalSoundnessNotion2 + architecturalSoundnessNotion3;
        const totalSustainabilityNotion = sustainabilityNotion1 + sustainabilityNotion2 + sustainabilityNotion3;
        const totalAccountabilityNotion = accountabilityNotion1 + accountabilityNotion2;


        return (
            getWeightValidationMessage("Pillars", totalPillar) ||
            getWeightValidationMessage("Robustness notions", totalRobustnessNotion) ||
            getWeightValidationMessage("Privacy notions", totalPrivacyNotion) ||
            getWeightValidationMessage("Fairness notions", totalFairnessNotion) ||
            getWeightValidationMessage("Explainability notions", totalExplainabilityNotion) ||
            getWeightValidationMessage("Architectural soundness notions", totalArchitecturalSoundnessNotion) ||
            getWeightValidationMessage("Sustainability notions", totalSustainabilityNotion) ||
            getWeightValidationMessage("Accountability notions", totalAccountabilityNotion)
        );
    }

    function validateWeightsDFL() {
        const robustnessPercent = parseFloat(document.getElementById("dfl-robustness-pillar").value) || 0;
        const privacyPercent = parseFloat(document.getElementById("dfl-privacy-pillar").value) || 0;
        const fairnessPercent = parseFloat(document.getElementById("dfl-fairness-pillar").value) || 0;
        const explainabilityPercent = parseFloat(document.getElementById("dfl-explainability-pillar").value) || 0;
        const accountabilityPercent = parseFloat(document.getElementById("dfl-accountability-pillar").value) || 0;
        const architecturalSoundnessPercent = parseFloat(document.getElementById("dfl-architectural-soundness-pillar").value) || 0;
        const sustainabilityPercent = parseFloat(document.getElementById("dfl-sustainability-pillar").value) || 0;

        const robustnessNotion1 = parseFloat(document.getElementById("dfl-robustness-notion-1").value) || 0;
        const robustnessNotion2 = parseFloat(document.getElementById("dfl-robustness-notion-2").value) || 0;
        const robustnessNotion3 = parseFloat(document.getElementById("dfl-robustness-notion-3").value) || 0;

        const privacyNotion1 = parseFloat(document.getElementById("dfl-privacy-notion-1").value) || 0;
        const privacyNotion2 = parseFloat(document.getElementById("dfl-privacy-notion-2").value) || 0;
        const privacyNotion3 = parseFloat(document.getElementById("dfl-privacy-notion-3").value) || 0;

        const fairnessNotion3 = parseFloat(document.getElementById("dfl-fairness-notion-3").value) || 0;
        const fairnessNotion4 = parseFloat(document.getElementById("dfl-fairness-notion-4").value) || 0;

        const explainabilityNotion1 = parseFloat(document.getElementById("dfl-explainability-notion-1").value) || 0;
        const explainabilityNotion2 = parseFloat(document.getElementById("dfl-explainability-notion-2").value) || 0;

        const architecturalSoundnessNotion1 = parseFloat(document.getElementById("dfl-architectural-soundness-notion-1").value) || 0;
        const architecturalSoundnessNotion2 = parseFloat(document.getElementById("dfl-architectural-soundness-notion-2").value) || 0;
        const architecturalSoundnessNotion3 = parseFloat(document.getElementById("dfl-architectural-soundness-notion-3").value) || 0;

        const sustainabilityNotion1 = parseFloat(document.getElementById("dfl-sustainability-notion-1").value) || 0;
        const sustainabilityNotion3 = parseFloat(document.getElementById("dfl-sustainability-notion-3").value) || 0;

        const accountabilityNotion1 = parseFloat(document.getElementById("cfl-accountability-notion-1").value) || 0;
        const accountabilityNotion2 = parseFloat(document.getElementById("cfl-accountability-notion-2").value) || 0;

        const totalPillar =
            robustnessPercent + privacyPercent + fairnessPercent + explainabilityPercent +
            accountabilityPercent + architecturalSoundnessPercent + sustainabilityPercent;

        const totalRobustnessNotion = robustnessNotion1 + robustnessNotion2 + robustnessNotion3;
        const totalPrivacyNotion = privacyNotion1 + privacyNotion2 + privacyNotion3;
        const totalFairnessNotion = fairnessNotion3 + fairnessNotion4;
        const totalExplainabilityNotion = explainabilityNotion1 + explainabilityNotion2;
        const totalArchitecturalSoundnessNotion = architecturalSoundnessNotion1 + architecturalSoundnessNotion2 + architecturalSoundnessNotion3;
        const totalSustainabilityNotion = sustainabilityNotion1 + sustainabilityNotion3;
        const totalAccountabilityNotion = accountabilityNotion1 + accountabilityNotion2;

        return (
            getWeightValidationMessage("Pillars", totalPillar) ||
            getWeightValidationMessage("Robustness notions", totalRobustnessNotion) ||
            getWeightValidationMessage("Privacy notions", totalPrivacyNotion) ||
            getWeightValidationMessage("Fairness notions", totalFairnessNotion) ||
            getWeightValidationMessage("Explainability notions", totalExplainabilityNotion) ||
            getWeightValidationMessage("Architectural soundness notions", totalArchitecturalSoundnessNotion) ||
            getWeightValidationMessage("Sustainability notions", totalSustainabilityNotion) ||
            getWeightValidationMessage("Accountability notions", totalAccountabilityNotion)
        );
    }

    function getTrustworthinessConfig() {
        const enabled = document.getElementById("trustworthiness-options").style.display === "block";
        const federationArchitecture = document.getElementById("federationArchitecture").value;

        if (isDFL()) return getTrustworthinessConfigDFL(enabled, federationArchitecture);
        return getTrustworthinessConfigCFL(enabled, federationArchitecture);
    }

    function getTrustworthinessConfigCFL(enabled, federationArchitecture) {
        const pillars = {
            robustness: parseFloat(document.getElementById("cfl-robustness-pillar").value) || 0,
            privacy: parseFloat(document.getElementById("cfl-privacy-pillar").value) || 0,
            fairness: parseFloat(document.getElementById("cfl-fairness-pillar").value) || 0,
            explainability: parseFloat(document.getElementById("cfl-explainability-pillar").value) || 0,
            accountability: parseFloat(document.getElementById("cfl-accountability-pillar").value) || 0,
            architecturalSoundness: parseFloat(document.getElementById("cfl-architectural-soundness-pillar").value) || 0,
            sustainability: parseFloat(document.getElementById("cfl-sustainability-pillar").value) || 0
        };

        const notions = {
            robustness: [
                parseFloat(document.getElementById("cfl-robustness-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-robustness-notion-2").value) || 0,
                parseFloat(document.getElementById("cfl-robustness-notion-3").value) || 0
            ],
            privacy: [
                parseFloat(document.getElementById("cfl-privacy-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-privacy-notion-2").value) || 0,
                parseFloat(document.getElementById("cfl-privacy-notion-3").value) || 0
            ],
            fairness: [
                parseFloat(document.getElementById("cfl-fairness-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-fairness-notion-2").value) || 0,
                parseFloat(document.getElementById("cfl-fairness-notion-3").value) || 0,
                parseFloat(document.getElementById("cfl-fairness-notion-4").value) || 0
            ],
            explainability: [
                parseFloat(document.getElementById("cfl-explainability-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-explainability-notion-2").value) || 0
            ],
            accountability: [
                parseFloat(document.getElementById("cfl-accountability-notion-1")?.value) || 0,
                parseFloat(document.getElementById("cfl-accountability-notion-2")?.value) || 0
            ],
            architecturalSoundness: [
                parseFloat(document.getElementById("cfl-architectural-soundness-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-architectural-soundness-notion-2").value) || 0,
                parseFloat(document.getElementById("cfl-architectural-soundness-notion-3").value) || 0
            ],
            sustainability: [
                parseFloat(document.getElementById("cfl-sustainability-notion-1").value) || 0,
                parseFloat(document.getElementById("cfl-sustainability-notion-2").value) || 0,
                parseFloat(document.getElementById("cfl-sustainability-notion-3").value) || 0
            ]
        };

        return { enabled, federationArchitecture, pillars, notions };
    }

    function getTrustworthinessConfigDFL(enabled, federationArchitecture) {
        const pillars = {
            robustness: parseFloat(document.getElementById("dfl-robustness-pillar").value) || 0,
            privacy: parseFloat(document.getElementById("dfl-privacy-pillar").value) || 0,
            fairness: parseFloat(document.getElementById("dfl-fairness-pillar").value) || 0,
            explainability: parseFloat(document.getElementById("dfl-explainability-pillar").value) || 0,
            accountability: parseFloat(document.getElementById("dfl-accountability-pillar").value) || 0,
            architecturalSoundness: parseFloat(document.getElementById("dfl-architectural-soundness-pillar").value) || 0,
            sustainability: parseFloat(document.getElementById("dfl-sustainability-pillar").value) || 0
        };

        const notions = {
            robustness: [
                parseFloat(document.getElementById("dfl-robustness-notion-1").value) || 0,
                parseFloat(document.getElementById("dfl-robustness-notion-2").value) || 0,
                parseFloat(document.getElementById("dfl-robustness-notion-3").value) || 0
            ],
            privacy: [
                parseFloat(document.getElementById("dfl-privacy-notion-1").value) || 0,
                parseFloat(document.getElementById("dfl-privacy-notion-2").value) || 0,
                parseFloat(document.getElementById("dfl-privacy-notion-3").value) || 0
            ],
            fairness: [
                parseFloat(document.getElementById("dfl-fairness-notion-3").value) || 0,
                parseFloat(document.getElementById("dfl-fairness-notion-4").value) || 0
            ],
            explainability: [
                parseFloat(document.getElementById("dfl-explainability-notion-1").value) || 0,
                parseFloat(document.getElementById("dfl-explainability-notion-2").value) || 0
            ],
            accountability: [
                parseFloat(document.getElementById("dfl-accountability-notion-1")?.value) || 0,
                parseFloat(document.getElementById("dfl-accountability-notion-2")?.value) || 0
            ],
            architecturalSoundness: [
                parseFloat(document.getElementById("dfl-architectural-soundness-notion-1").value) || 0,
                parseFloat(document.getElementById("dfl-architectural-soundness-notion-2").value) || 0,
                parseFloat(document.getElementById("dfl-architectural-soundness-notion-3").value) || 0
            ],
            sustainability: [
                parseFloat(document.getElementById("dfl-sustainability-notion-1").value) || 0,
                parseFloat(document.getElementById("dfl-sustainability-notion-3").value) || 0
            ]
        };

        return { enabled, federationArchitecture, pillars, notions };
    }

    function setTrustworthinessConfig(config) {
        if (!config) return;

        if (isDFL()) setTrustworthinessConfigDFL(config);
        else setTrustworthinessConfigCFL(config);

        validateWeights();
    }

    function setTrustworthinessConfigCFL(config) {
        if (config.pillars) {
            document.getElementById("cfl-robustness-pillar").value = config.pillars.robustness || 0;
            document.getElementById("cfl-privacy-pillar").value = config.pillars.privacy || 0;
            document.getElementById("cfl-fairness-pillar").value = config.pillars.fairness || 0;
            document.getElementById("cfl-explainability-pillar").value = config.pillars.explainability || 0;
            document.getElementById("cfl-accountability-pillar").value = config.pillars.accountability || 0;
            document.getElementById("cfl-architectural-soundness-pillar").value = config.pillars.architecturalSoundness || 0;
            document.getElementById("cfl-sustainability-pillar").value = config.pillars.sustainability || 0;
        }

        if (config.notions) {
            const r = config.notions.robustness || [0, 0, 0];
            document.getElementById("cfl-robustness-notion-1").value = r[0];
            document.getElementById("cfl-robustness-notion-2").value = r[1];
            document.getElementById("cfl-robustness-notion-3").value = r[2];

            const p = config.notions.privacy || [0, 0, 0];
            document.getElementById("cfl-privacy-notion-1").value = p[0];
            document.getElementById("cfl-privacy-notion-2").value = p[1];
            document.getElementById("cfl-privacy-notion-3").value = p[2];

            const f = config.notions.fairness || [0, 0, 0, 0];
            document.getElementById("cfl-fairness-notion-1").value = f[0];
            document.getElementById("cfl-fairness-notion-2").value = f[1];
            document.getElementById("cfl-fairness-notion-3").value = f[2];
            document.getElementById("cfl-fairness-notion-4").value = f[3];

            const e = config.notions.explainability || [0, 0];
            document.getElementById("cfl-explainability-notion-1").value = e[0];
            document.getElementById("cfl-explainability-notion-2").value = e[1];

            const a = config.notions.architecturalSoundness || [0, 0, 0];
            document.getElementById("cfl-architectural-soundness-notion-1").value = a[0];
            document.getElementById("cfl-architectural-soundness-notion-2").value = a[1];
            document.getElementById("cfl-architectural-soundness-notion-3").value = a[2];

            const s = config.notions.sustainability || [0, 0, 0];
            document.getElementById("cfl-sustainability-notion-1").value = s[0];
            document.getElementById("cfl-sustainability-notion-2").value = s[1];
            document.getElementById("cfl-sustainability-notion-3").value = s[2];
        }
    }

    function setTrustworthinessConfigDFL(config) {
        if (config.pillars) {
            document.getElementById("dfl-robustness-pillar").value = config.pillars.robustness || 0;
            document.getElementById("dfl-privacy-pillar").value = config.pillars.privacy || 0;
            document.getElementById("dfl-fairness-pillar").value = config.pillars.fairness || 0;
            document.getElementById("dfl-explainability-pillar").value = config.pillars.explainability || 0;
            document.getElementById("dfl-accountability-pillar").value = config.pillars.accountability || 0;
            document.getElementById("dfl-architectural-soundness-pillar").value = config.pillars.architecturalSoundness || 0;
            document.getElementById("dfl-sustainability-pillar").value = config.pillars.sustainability || 0;
        }

        if (config.notions) {
            const r = config.notions.robustness || [0, 0, 0];
            document.getElementById("dfl-robustness-notion-1").value = r[0];
            document.getElementById("dfl-robustness-notion-2").value = r[1];
            document.getElementById("dfl-robustness-notion-3").value = r[2];

            const p = config.notions.privacy || [0, 0, 0];
            document.getElementById("dfl-privacy-notion-1").value = p[0];
            document.getElementById("dfl-privacy-notion-2").value = p[1];
            document.getElementById("dfl-privacy-notion-3").value = p[2];

            const f = config.notions.fairness || [0, 0];
            document.getElementById("dfl-fairness-notion-3").value = f[0];
            document.getElementById("dfl-fairness-notion-4").value = f[1];

            const e = config.notions.explainability || [0, 0];
            document.getElementById("dfl-explainability-notion-1").value = e[0];
            document.getElementById("dfl-explainability-notion-2").value = e[1];

            const a = config.notions.architecturalSoundness || [0, 0, 0];
            document.getElementById("dfl-architectural-soundness-notion-1").value = a[0];
            document.getElementById("dfl-architectural-soundness-notion-2").value = a[1];
            document.getElementById("dfl-architectural-soundness-notion-3").value = a[2];

            const s = config.notions.sustainability || [0, 0];
            document.getElementById("dfl-sustainability-notion-1").value = s[0];
            document.getElementById("dfl-sustainability-notion-3").value = s[1];
        }
    }

    function resetTrustworthinessConfig() {
        const trustworthinessOptionsDiv = document.getElementById("trustworthiness-options");
        const fedArchElement = document.getElementById("federationArchitecture");

        trustworthinessOptionsDiv.style.display = "none";
        fedArchElement.disabled = false;

        if (isDFL()) resetTrustworthinessConfigDFL();
        else resetTrustworthinessConfigCFL();

        validateWeights();
    }

    function resetTrustworthinessConfigCFL() {
        document.getElementById("cfl-robustness-pillar").value = "0";
        document.getElementById("cfl-privacy-pillar").value = "0";
        document.getElementById("cfl-fairness-pillar").value = "0";
        document.getElementById("cfl-explainability-pillar").value = "0";
        document.getElementById("cfl-accountability-pillar").value = "0";
        document.getElementById("cfl-architectural-soundness-pillar").value = "0";
        document.getElementById("cfl-sustainability-pillar").value = "0";

        document.getElementById("cfl-robustness-notion-1").value = "0";
        document.getElementById("cfl-robustness-notion-2").value = "0";
        document.getElementById("cfl-robustness-notion-3").value = "0";

        document.getElementById("cfl-privacy-notion-1").value = "0";
        document.getElementById("cfl-privacy-notion-2").value = "0";
        document.getElementById("cfl-privacy-notion-3").value = "0";

        document.getElementById("cfl-fairness-notion-1").value = "0";
        document.getElementById("cfl-fairness-notion-2").value = "0";
        document.getElementById("cfl-fairness-notion-3").value = "0";
        document.getElementById("cfl-fairness-notion-4").value = "0";

        document.getElementById("cfl-explainability-notion-1").value = "0";
        document.getElementById("cfl-explainability-notion-2").value = "0";

        document.getElementById("cfl-architectural-soundness-notion-1").value = "0";
        document.getElementById("cfl-architectural-soundness-notion-2").value = "0";
        document.getElementById("cfl-architectural-soundness-notion-3").value = "0";

        document.getElementById("cfl-sustainability-notion-1").value = "0";
        document.getElementById("cfl-sustainability-notion-2").value = "0";
        document.getElementById("cfl-sustainability-notion-3").value = "0";
    }

    function resetTrustworthinessConfigDFL() {
        document.getElementById("dfl-robustness-pillar").value = "0";
        document.getElementById("dfl-privacy-pillar").value = "0";
        document.getElementById("dfl-fairness-pillar").value = "0";
        document.getElementById("dfl-explainability-pillar").value = "0";
        document.getElementById("dfl-accountability-pillar").value = "0";
        document.getElementById("dfl-architectural-soundness-pillar").value = "0";
        document.getElementById("dfl-sustainability-pillar").value = "0";

        document.getElementById("dfl-robustness-notion-1").value = "0";
        document.getElementById("dfl-robustness-notion-2").value = "0";
        document.getElementById("dfl-robustness-notion-3").value = "0";

        document.getElementById("dfl-privacy-notion-1").value = "0";
        document.getElementById("dfl-privacy-notion-2").value = "0";
        document.getElementById("dfl-privacy-notion-3").value = "0";

        document.getElementById("dfl-fairness-notion-3").value = "0";
        document.getElementById("dfl-fairness-notion-4").value = "0";

        document.getElementById("dfl-explainability-notion-1").value = "0";
        document.getElementById("dfl-explainability-notion-2").value = "0";

        document.getElementById("dfl-architectural-soundness-notion-1").value = "0";
        document.getElementById("dfl-architectural-soundness-notion-2").value = "0";
        document.getElementById("dfl-architectural-soundness-notion-3").value = "0";

        document.getElementById("dfl-sustainability-notion-1").value = "0";
        document.getElementById("dfl-sustainability-notion-3").value = "0";
    }

    return {
        initializeTrustworthinessSystem,
        getTrustworthinessConfig,
        setTrustworthinessConfig,
        resetTrustworthinessConfig,
        validateWeights
    };
})();

export default TrustworthinessManager;
