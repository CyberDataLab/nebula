// Trustworthiness System Module
const TrustworthinessManager = (function() {
    function initializeTrustworthinessSystem() {
        setupTrustworthinessSwitch();
        setupWeightValidation();
    }
 
    function setupTrustworthinessSwitch() {
        document.getElementById("TrustworthinessSwitch").addEventListener("change", function() {
            const trustworthinessOptionsDiv = document.getElementById("trustworthiness-options");
            
            if(this.checked){
                document.getElementById("federationArchitecture").value = "CFL";
                document.getElementById("federationArchitecture").dispatchEvent(new Event('change'));
                document.getElementById("federationArchitecture").disabled = true;
                trustworthinessOptionsDiv.style.display = "block"
            } else {
                document.getElementById("federationArchitecture").disabled = false;
                trustworthinessOptionsDiv.style.display = "none";
            }
        });
    }
 
    function setupWeightValidation() {
        const pillarIds = [
            "robustness-pillar",
            "privacy-pillar",
            "fairness-pillar",
            "explainability-pillar",
            "accountability-pillar",
            "architectural-soundness-pillar",
            "sustainability-pillar"
        ];
        const notionIds = [
            "robustness-notion-1",
            "robustness-notion-2",
            "robustness-notion-3",
            "privacy-notion-1",
            "privacy-notion-2",
            "privacy-notion-3",
            "fairness-notion-1",
            "fairness-notion-2",
            "fairness-notion-3",
            "explainability-notion-1",
            "explainability-notion-2",
            "architectural-soundness-notion-1",
            "architectural-soundness-notion-2",
            "sustainability-notion-1",
            "sustainability-notion-2",
            "sustainability-notion-3"
        ];
 
        pillarIds.concat(notionIds).forEach(id => {
            const input = document.getElementById(id);
            if (input) {
                input.addEventListener("input", validateWeights);
            }
        });
    }
 
    function validateWeights() {
        const robustnessPercent = parseFloat(document.getElementById("robustness-pillar").value) || 0;
        const privacyPercent = parseFloat(document.getElementById("privacy-pillar").value) || 0;
        const fairnessPercent = parseFloat(document.getElementById("fairness-pillar").value) || 0;
        const explainabilityPercent = parseFloat(document.getElementById("explainability-pillar").value) || 0;
        const accountabilityPercent = parseFloat(document.getElementById("accountability-pillar").value) || 0;
        const architecturalSoundnessPercent = parseFloat(document.getElementById("architectural-soundness-pillar").value) || 0;
        const sustainabilityPercent = parseFloat(document.getElementById("sustainability-pillar").value) || 0;
 
        const robustnessNotion1 = parseFloat(document.getElementById("robustness-notion-1").value) || 0;
        const robustnessNotion2 = parseFloat(document.getElementById("robustness-notion-2").value) || 0;
        const robustnessNotion3 = parseFloat(document.getElementById("robustness-notion-3").value) || 0;
        const privacyNotion1 = parseFloat(document.getElementById("privacy-notion-1").value) || 0;
        const privacyNotion2 = parseFloat(document.getElementById("privacy-notion-2").value) || 0;
        const privacyNotion3 = parseFloat(document.getElementById("privacy-notion-3").value) || 0;
        const fairnessNotion1 = parseFloat(document.getElementById("fairness-notion-1").value) || 0;
        const fairnessNotion2 = parseFloat(document.getElementById("fairness-notion-2").value) || 0;
        const fairnessNotion3 = parseFloat(document.getElementById("fairness-notion-3").value) || 0;
        const explainabilityNotion1 = parseFloat(document.getElementById("explainability-notion-1").value) || 0;
        const explainabilityNotion2 = parseFloat(document.getElementById("explainability-notion-2").value) || 0;
        const architecturalSoundnessNotion1 = parseFloat(document.getElementById("architectural-soundness-notion-1").value) || 0;
        const architecturalSoundnessNotion2 = parseFloat(document.getElementById("architectural-soundness-notion-2").value) || 0;
        const sustainabilityNotion1 = parseFloat(document.getElementById("sustainability-notion-1").value) || 0;
        const sustainabilityNotion2 = parseFloat(document.getElementById("sustainability-notion-2").value) || 0;
        const sustainabilityNotion3 = parseFloat(document.getElementById("sustainability-notion-3").value) || 0;
 
        const totalPillar =
            robustnessPercent +
            privacyPercent +
            fairnessPercent +
            explainabilityPercent +
            accountabilityPercent +
            architecturalSoundnessPercent +
            sustainabilityPercent;
 
        const totalRobustnessNotion = robustnessNotion1 + robustnessNotion2 + robustnessNotion3;
        const totalPrivacyNotion = privacyNotion1 + privacyNotion2 + privacyNotion3;
        const totalFairnessNotion = fairnessNotion1 + fairnessNotion2 + fairnessNotion3;
        const totalExplainabilityNotion = explainabilityNotion1 + explainabilityNotion2;
        const totalArchitecturalSoundnessNotion = architecturalSoundnessNotion1 + architecturalSoundnessNotion2;
        const totalSustainabilityNotion = sustainabilityNotion1 + sustainabilityNotion2 + sustainabilityNotion3;
 
        if (totalPillar !== 100) {
            return "[Trustworthiness] Check pillars weights";
        }
        if (totalRobustnessNotion !== 100) {
            return "[Trustworthiness] Check robustness notions weights";
        }
        if (totalPrivacyNotion !== 100) {
            return "[Trustworthiness] Check privacy notions weights";
        }
        if (totalFairnessNotion !== 100) {
            return "[Trustworthiness] Check fairness notions weights";
        }
        if (totalExplainabilityNotion !== 100) {
            return "[Trustworthiness] Check explainability notions weights";
        }
        if (totalArchitecturalSoundnessNotion !== 100) {
            return "[Trustworthiness] Check architectural soundness notions weights";
        }
        if (totalSustainabilityNotion !== 100) {
            return "[Trustworthiness] Check sustainability notions weights";
        }
    }
 
    function getTrustworthinessConfig() {
        const enabled = document.getElementById("trustworthiness-options").style.display === "block";
        const federationArchitecture = document.getElementById("federationArchitecture").value;
 
        const pillars = {
            robustness: parseFloat(document.getElementById("robustness-pillar").value) || 0,
            privacy: parseFloat(document.getElementById("privacy-pillar").value) || 0,
            fairness: parseFloat(document.getElementById("fairness-pillar").value) || 0,
            explainability: parseFloat(document.getElementById("explainability-pillar").value) || 0,
            accountability: parseFloat(document.getElementById("accountability-pillar").value) || 0,
            architecturalSoundness: parseFloat(document.getElementById("architectural-soundness-pillar").value) || 0,
            sustainability: parseFloat(document.getElementById("sustainability-pillar").value) || 0
        };
 
        const notions = {
            robustness: [
                parseFloat(document.getElementById("robustness-notion-1").value) || 0,
                parseFloat(document.getElementById("robustness-notion-2").value) || 0,
                parseFloat(document.getElementById("robustness-notion-3").value) || 0
            ],
            privacy: [
                parseFloat(document.getElementById("privacy-notion-1").value) || 0,
                parseFloat(document.getElementById("privacy-notion-2").value) || 0,
                parseFloat(document.getElementById("privacy-notion-3").value) || 0
            ],
            fairness: [
                parseFloat(document.getElementById("fairness-notion-1").value) || 0,
                parseFloat(document.getElementById("fairness-notion-2").value) || 0,
                parseFloat(document.getElementById("fairness-notion-3").value) || 0
            ],
            explainability: [
                parseFloat(document.getElementById("explainability-notion-1").value) || 0,
                parseFloat(document.getElementById("explainability-notion-2").value) || 0
            ],
            architecturalSoundness: [
                parseFloat(document.getElementById("architectural-soundness-notion-1").value) || 0,
                parseFloat(document.getElementById("architectural-soundness-notion-2").value) || 0
            ],
            sustainability: [
                parseFloat(document.getElementById("sustainability-notion-1").value) || 0,
                parseFloat(document.getElementById("sustainability-notion-2").value) || 0,
                parseFloat(document.getElementById("sustainability-notion-3").value) || 0
            ]
        };
 
        return {
            enabled,
            federationArchitecture,
            pillars,
            notions
        };
    }
 
    function setTrustworthinessConfig(config) {
        if (!config) return;
 
        // Set pillar weights
        if (config.pillars) {
            document.getElementById("robustness-pillar").value = config.pillars.robustness || 0;
            document.getElementById("privacy-pillar").value = config.pillars.privacy || 0;
            document.getElementById("fairness-pillar").value = config.pillars.fairness || 0;
            document.getElementById("explainability-pillar").value = config.pillars.explainability || 0;
            document.getElementById("accountability-pillar").value = config.pillars.accountability || 0;
            document.getElementById("architectural-soundness-pillar").value = config.pillars.architecturalSoundness || 0;
            document.getElementById("sustainability-pillar").value = config.pillars.sustainability || 0;
        }
 
        // Set notion weights
        if (config.notions) {
            const rNotions = config.notions.robustness || [0, 0, 0];
            document.getElementById("robustness-notion-1").value = rNotions[0];
            document.getElementById("robustness-notion-2").value = rNotions[1];
            document.getElementById("robustness-notion-3").value = rNotions[2];
 
            const pNotions = config.notions.privacy || [0, 0, 0];
            document.getElementById("privacy-notion-1").value = pNotions[0];
            document.getElementById("privacy-notion-2").value = pNotions[1];
            document.getElementById("privacy-notion-3").value = pNotions[2];
 
            const fNotions = config.notions.fairness || [0, 0, 0];
            document.getElementById("fairness-notion-1").value = fNotions[0];
            document.getElementById("fairness-notion-2").value = fNotions[1];
            document.getElementById("fairness-notion-3").value = fNotions[2];
 
            const eNotions = config.notions.explainability || [0, 0];
            document.getElementById("explainability-notion-1").value = eNotions[0];
            document.getElementById("explainability-notion-2").value = eNotions[1];
 
            const aNotions = config.notions.architecturalSoundness || [0, 0];
            document.getElementById("architectural-soundness-notion-1").value = aNotions[0];
            document.getElementById("architectural-soundness-notion-2").value = aNotions[1];
 
            const sNotions = config.notions.sustainability || [0, 0, 0];
            document.getElementById("sustainability-notion-1").value = sNotions[0];
            document.getElementById("sustainability-notion-2").value = sNotions[1];
            document.getElementById("sustainability-notion-3").value = sNotions[2];
        }
 
        // Perform a weight validation check to update any warnings if needed
        validateWeights();
    }
 
    function resetTrustworthinessConfig() {
        const trustworthinessOptionsDiv = document.getElementById("trustworthiness-options");
        const fedArchElement = document.getElementById("federationArchitecture");
 
        // Hide options and re-enable federationArchitecture
        trustworthinessOptionsDiv.style.display = "none";
        fedArchElement.disabled = false;
 
        // Reset pillars to 0
        document.getElementById("robustness-pillar").value = "0";
        document.getElementById("privacy-pillar").value = "0";
        document.getElementById("fairness-pillar").value = "0";
        document.getElementById("explainability-pillar").value = "0";
        document.getElementById("accountability-pillar").value = "0";
        document.getElementById("architectural-soundness-pillar").value = "0";
        document.getElementById("sustainability-pillar").value = "0";
 
        // Reset notions to 0
        document.getElementById("robustness-notion-1").value = "0";
        document.getElementById("robustness-notion-2").value = "0";
        document.getElementById("robustness-notion-3").value = "0";
        document.getElementById("privacy-notion-1").value = "0";
        document.getElementById("privacy-notion-2").value = "0";
        document.getElementById("privacy-notion-3").value = "0";
        document.getElementById("fairness-notion-1").value = "0";
        document.getElementById("fairness-notion-2").value = "0";
        document.getElementById("fairness-notion-3").value = "0";
        document.getElementById("explainability-notion-1").value = "0";
        document.getElementById("explainability-notion-2").value = "0";
        document.getElementById("architectural-soundness-notion-1").value = "0";
        document.getElementById("architectural-soundness-notion-2").value = "0";
        document.getElementById("sustainability-notion-1").value = "0";
        document.getElementById("sustainability-notion-2").value = "0";
        document.getElementById("sustainability-notion-3").value = "0";
 
        // Re-validate weights after reset
        validateWeights();
    }
 
    return {
        initializeTrustworthinessSystem,
        getTrustworthinessConfig,
        setTrustworthinessConfig,
        resetTrustworthinessConfig
    };
})();
 
export default TrustworthinessManager;