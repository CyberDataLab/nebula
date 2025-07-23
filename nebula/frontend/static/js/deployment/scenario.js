// Scenario Management Module
const ScenarioManager = (function() {
    let scenariosList = [];
    let actual_scenario = 0;
    let physical_ips     = [];
    let isLoadingScenario = false;
    let isNavigating = false;  // Flag to prevent auto-save during navigation

    // Initialize scenarios from session storage
    function initializeScenarios() {
        // Clear session storage
        sessionStorage.removeItem("ScenarioList");

        // Reset the scenarios list
        scenariosList = [];
        actual_scenario = 0;

        // Clear all fields and reset modules
        clearFields();

        // Update UI
        updateScenariosPosition(true);

        // Setup automatic saving when topology changes
        setupTopologyAutoSave();
    }

    function setupTopologyAutoSave() {
        // Listen for topology changes and auto-save the scenario
        document.addEventListener('graphDataUpdated', function() {
            // Only auto-save if we have existing scenarios and we're not currently loading or navigating
            if (scenariosList.length > 0 && !isLoadingScenario && !isNavigating) {
                console.log('Topology changed, auto-saving scenario...', {
                    actualScenario: actual_scenario,
                    scenariosCount: scenariosList.length,
                    isLoading: isLoadingScenario,
                    isNavigating: isNavigating
                });
                replaceScenario();
                console.log('Auto-save completed');
            } else {
                console.log('Topology changed but auto-save skipped:', {
                    hasScenarios: scenariosList.length > 0,
                    isLoading: isLoadingScenario,
                    isNavigating: isNavigating
                });
            }
        });
    }

    function collectScenarioData() {
        window.TopologyManager.updateGraph();
        const topologyData = window.TopologyManager.getData();
        const nodes = {};
        const nodes_graph = {};
        // Convert nodes array to objects with string IDs
        topologyData.nodes.forEach(node => {
            const nodeId = node.id.toString();
            nodes[nodeId] = {
                id: nodeId,
                ip: node.ip,
                port: node.port,
                role: node.role,
                malicious: node.malicious,
                proxy: node.proxy,
                start: node.start,
                neighbors: node.neighbors.map(n => n.toString()),
                links: node.links,
            };
            nodes_graph[nodeId] = {
                id: nodeId,
                role: node.role,
                malicious: node.malicious,
                proxy: node.proxy,
                start: node.start
            };
        });

        // Get topology type from select element
        const topologyType = document.getElementById('predefined-topology-select').value;

        // Get attack configuration
        const attackConfig = window.AttackManager.getAttackConfig();

        // Get training configuration
        const trainingConfig = window.TrainingManager.getTrainingConfig();

        // Validate that we have required fields
        const scenarioTitle = document.getElementById("scenario-title").value.trim();
        const dataset = document.getElementById("datasetSelect").value;
        const model = document.getElementById("modelSelect").value;

        if (!scenarioTitle) {
            console.warn("Scenario title is empty, using default");
        }

        return {
            scenario_title: document.getElementById("scenario-title").value,
            scenario_description: document.getElementById("scenario-description").value,
            deployment: document.querySelector('input[name="deploymentRadioOptions"]:checked').value,
            federation: document.getElementById("federationArchitecture").value,
            rounds: parseInt(document.getElementById("rounds").value),
            topology: topologyType,
            nodes: nodes,
            nodes_graph: nodes_graph,
            n_nodes: topologyData.nodes.length,
            matrix: window.TopologyManager.getMatrix(),
            dataset: document.getElementById("datasetSelect").value,
            iid: document.getElementById("iidSelect").value === "true",
            partition_selection: document.getElementById("partitionSelect").value,
            partition_parameter: parseFloat(document.getElementById("partitionParameter").value),
            remove_classes_count: parseInt(document.getElementById("removeClassesCount").value) || 0,
            model: document.getElementById("modelSelect").value,
            agg_algorithm: document.getElementById("aggregationSelect").value,
            logginglevel: document.getElementById("loggingLevel").value === "true",
            report_status_data_queue: document.getElementById("reportingSwitch").checked,
            epochs: trainingConfig.epochs,
            communication_mode: trainingConfig.communication_mode,
            batches_per_communication: trainingConfig.batches_per_communication,
            attack_params: attackConfig,
            reputation: window.ReputationManager.getReputationConfig(),
            mobility: window.MobilityManager.getMobilityConfig().enabled || false,
            network_simulation: window.MobilityManager.getMobilityConfig().network_simulation || false,
            mobility_type: window.MobilityManager.getMobilityConfig().mobilityType || "random",
            radius_federation: window.MobilityManager.getMobilityConfig().radiusFederation || 1000,
            scheme_mobility: window.MobilityManager.getMobilityConfig().schemeMobility || "random",
            round_frequency: window.MobilityManager.getMobilityConfig().roundFrequency || 1,
            mobile_participants_percent: window.MobilityManager.getMobilityConfig().mobileParticipantsPercent || 0.5,
            random_geo: window.MobilityManager.getMobilityConfig().randomGeo || false,
            latitude: window.MobilityManager.getMobilityConfig().location.latitude || 0,
            longitude: window.MobilityManager.getMobilityConfig().location.longitude || 0,
            with_sa: window.SaManager.getSaConfig().with_sa || false,
            strict_topology: window.SaManager.getSaConfig().strict_topology || false,
            sad_candidate_selector: window.SaManager.getSaConfig().sad_candidate_selector || "Distance",
            sad_model_handler: window.SaManager.getSaConfig().sad_model_handler || "std",
            sar_arbitration_policy: window.SaManager.getSaConfig().sar_arbitration_policy || "sap",
            sar_neighbor_policy: window.SaManager.getSaConfig().sar_neighbor_policy || "Distance",
            sar_training: window.SaManager.getSaConfig().sar_training || false,
            sar_training_policy: window.SaManager.getSaConfig().sar_training_policy || "Broad-Propagation Strategy",
            random_topology_probability: document.getElementById("random-probability").value || 0.5,
            with_trustworthiness: document.getElementById("TrustworthinessSwitch").checked ? true : false,
            robustness_pillar: document.getElementById("robustness-pillar").value,
            resilience_to_attacks: document.getElementById("robustness-notion-1").value,
            algorithm_robustness: document.getElementById("robustness-notion-2").value,
            client_reliability: document.getElementById("robustness-notion-3").value,
            privacy_pillar: document.getElementById("privacy-pillar").value,
            technique: document.getElementById("privacy-notion-1").value,
            uncertainty: document.getElementById("privacy-notion-2").value,
            indistinguishability: document.getElementById("privacy-notion-3").value,
            fairness_pillar: document.getElementById("fairness-pillar").value,
            selection_fairness: document.getElementById("fairness-notion-1").value,
            performance_fairness: document.getElementById("fairness-notion-2").value,
            class_distribution: document.getElementById("fairness-notion-3").value,
            explainability_pillar: document.getElementById("explainability-pillar").value,
            interpretability: document.getElementById("explainability-notion-1").value,
            post_hoc_methods: document.getElementById("explainability-notion-2").value,
            accountability_pillar: document.getElementById("accountability-pillar").value,
            factsheet_completeness: document.getElementById("accountability-notion-1").value,
            architectural_soundness_pillar: document.getElementById("architectural-soundness-pillar").value,
            client_management: document.getElementById("architectural-soundness-notion-1").value,
            optimization: document.getElementById("architectural-soundness-notion-2").value,
            sustainability_pillar: document.getElementById("sustainability-pillar").value,
            energy_source: document.getElementById("sustainability-notion-1").value,
            hardware_efficiency: document.getElementById("sustainability-notion-2").value,
            federation_complexity: document.getElementById("sustainability-notion-3").value,
            network_subnet: "172.20.0.0/16",
            network_gateway: "172.20.0.1",
            additional_participants: window.MobilityManager.getMobilityConfig().additionalParticipants || [],
            schema_additional_participants: document.getElementById("schemaAdditionalParticipantsSelect").value || "random",
            accelerator: "cpu",
            gpu_id: [],
            physical_ips: physical_ips
        };
    }

    function loadScenario(scenario) {
        if (!scenario) return;

        console.log('loadScenario: Loading scenario:', scenario.scenario_title);
        console.log('loadScenario: Topology data being loaded:', {
            topology: scenario.topology,
            n_nodes: scenario.n_nodes,
            nodes_count: Object.keys(scenario.nodes || {}).length,
            has_custom_topology: scenario.nodes && Object.keys(scenario.nodes).length > 0
        });

        // Mark that we're loading a scenario to prevent auto-save
        isLoadingScenario = true;

        // Load basic fields
        document.getElementById("scenario-title").value = scenario.scenario_title || "";
        document.getElementById("scenario-description").value = scenario.scenario_description || "";

        // Load deployment
        const deploymentRadio = document.querySelector(`input[name="deploymentRadioOptions"][value="${scenario.deployment}"]`);
        if (deploymentRadio) deploymentRadio.checked = true;

        // Load architecture and rounds
        document.getElementById("federationArchitecture").value = scenario.federation;
        document.getElementById("rounds").value = scenario.rounds;

        // Load topology configuration UI
        if (scenario.topology) {
            document.getElementById("predefined-topology-select").value = scenario.topology;
        }
        if (scenario.n_nodes) {
            document.getElementById("predefined-topology-nodes").value = scenario.n_nodes;
        }
        if (scenario.random_topology_probability) {
            document.getElementById("random-probability").value = scenario.random_topology_probability;
        }

        // Set topology type (predefined vs custom)
        if (scenario.nodes && scenario.nodes_graph && Object.keys(scenario.nodes).length > 0) {
            // If we have custom topology data, set to custom
            document.getElementById("custom-topology-btn").checked = true;
            document.getElementById("predefined-topology-btn").checked = false;
            document.getElementById("predefined-topology").style.display = "none";

            const topologyData = {
                nodes: Object.values(scenario.nodes),
                links: []
            };

            // Reconstruct links from the nodes' neighbors
            topologyData.nodes.forEach(node => {
                if (node.neighbors) {
                    node.neighbors.forEach(neighborId => {
                        topologyData.links.push({
                            source: node.id,
                            target: neighborId
                        });
                    });
                }
            });

            window.TopologyManager.setData(topologyData);
        } else {
            // If no custom topology data, set to predefined
            document.getElementById("predefined-topology-btn").checked = true;
            document.getElementById("custom-topology-btn").checked = false;
            document.getElementById("predefined-topology").style.display = "block";
            window.TopologyManager.generatePredefinedTopology();
        }

        /*  if "physical" assign the IPs again*/
        if (scenario.physical_ips) {
            setPhysicalIPs(scenario.physical_ips);
            window.TopologyManager.setPhysicalIPs(scenario.physical_ips);
        }

        // Load dataset settings
        document.getElementById("datasetSelect").value = scenario.dataset;
        document.getElementById("iidSelect").value = scenario.iid ? "true" : "false";
        document.getElementById("partitionSelect").value = scenario.partition_selection;
        document.getElementById("partitionParameter").value = scenario.partition_parameter;
        document.getElementById("removeClassesCount").value = scenario.remove_classes_count || 0;

        // Load aggregation first
        document.getElementById("aggregationSelect").value = scenario.agg_algorithm;

        // Load advanced settings
        document.getElementById("loggingLevel").value = scenario.logginglevel ? "true" : "false";
        document.getElementById("reportingSwitch").checked = scenario.report_status_data_queue;
        document.getElementById("epochs").value = scenario.epochs;

        // Load module configurations
        if (scenario.attacks && scenario.attacks.length > 0) {
            window.AttackManager.setAttackConfig({
                attacks: scenario.attacks,
                poisoned_node_percent: scenario.poisoned_node_percent,
                poisoned_sample_percent: scenario.poisoned_sample_percent,
                poisoned_noise_percent: scenario.poisoned_noise_percent,
                attack_params: scenario.attack_params
            });
        }
        if (scenario.mobility) {
            window.MobilityManager.setMobilityConfig({
                enabled: scenario.mobility,
                network_simulation: scenario.network_simulation,
                mobilityType: scenario.mobility_type,
                radiusFederation: scenario.radius_federation,
                schemeMobility: scenario.scheme_mobility,
                roundFrequency: scenario.round_frequency,
                mobileParticipantsPercent: scenario.mobile_participants_percent,
                randomGeo: scenario.random_geo,
                location: {
                    latitude: scenario.latitude,
                    longitude: scenario.longitude
                },
                additionalParticipants: scenario.additional_participants
            });
        }
        if (scenario.reputation && scenario.reputation.enabled) {
            window.ReputationManager.setReputationConfig({
                enabled: scenario.reputation.enabled,
                metrics: scenario.reputation.metrics || {},
                initialReputation: scenario.reputation.initialReputation || 0.2,
                weightingFactor: scenario.reputation.weighting_factor || "dynamic",
            });
        }
        if (scenario.with_sa) {
            window.SaManager.setSaConfig({
                with_sa: scenario.with_sa,
                strict_topology: scenario.strict_topology,
                sad_candidate_selector: scenario.sad_candidate_selector,
                sad_model_handler: scenario.sad_model_handler,
                sar_arbitration_policy: scenario.sar_arbitration_policy,
                sar_neighbor_policy: scenario.sar_neighbor_policy,
                sar_training: scenario.sar_training,
                sar_training_policy: scenario.sar_training_policy,
            });
        }

        // Trigger necessary events (this will update model options and topology)
        document.getElementById("federationArchitecture").dispatchEvent(new Event('change'));
        document.getElementById("datasetSelect").dispatchEvent(new Event('change'));
        document.getElementById("iidSelect").dispatchEvent(new Event('change'));

        // Trigger topology events to ensure UI is in sync
        if (document.getElementById("predefined-topology-btn").checked) {
            document.getElementById("predefined-topology-select").dispatchEvent(new Event('change'));
        }

        // Load model AFTER the dataset change event has updated the model options
        setTimeout(() => {
            const modelSelect = document.getElementById("modelSelect");
            const modelValue = scenario.model;

            // Check if the model is available in the current options
            const availableOptions = Array.from(modelSelect.options).map(option => option.value);

            if (availableOptions.includes(modelValue)) {
                modelSelect.value = modelValue;
            } else {
                console.warn(`Model "${modelValue}" not available for dataset "${scenario.dataset}". Using first available model.`);
                // Use the first available model if the configured one isn't available
                if (availableOptions.length > 0) {
                    modelSelect.value = availableOptions[0];
                }
            }
        }, 100);

        // Load training configuration
        const trainingConfig = {
            epochs: scenario.epochs,
            communication_mode: scenario.communication_mode || "epoch",
            batches_per_communication: scenario.batches_per_communication || 1
        };
        window.TrainingManager.setTrainingConfig(trainingConfig);

        // Mark loading as complete
        isLoadingScenario = false;
    }

    function saveScenario() {
        const scenarioData = collectScenarioData();
        scenariosList.push(scenarioData);
        actual_scenario = scenariosList.length - 1;
        sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
        updateScenariosPosition();
    }

    function deleteScenario() {
        if (scenariosList.length === 0) return;

        scenariosList.splice(actual_scenario, 1);
        if (actual_scenario >= scenariosList.length) {
            actual_scenario = Math.max(0, scenariosList.length - 1);
        }

        if (scenariosList.length > 0) {
            loadScenario(scenariosList[actual_scenario]);
        } else {
            clearFields();
        }

        sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
        updateScenariosPosition(scenariosList.length === 0);
    }

    function replaceScenario() {
        if (actual_scenario < 0 || actual_scenario >= scenariosList.length) {
            console.log('replaceScenario: Invalid scenario index', actual_scenario, 'of', scenariosList.length);
            return;
        }

        console.log('replaceScenario: Saving scenario', actual_scenario);
        const scenarioData = collectScenarioData();

        // Debug topology data
        console.log('replaceScenario: Topology data being saved:', {
            topology: scenarioData.topology,
            n_nodes: scenarioData.n_nodes,
            nodes_count: Object.keys(scenarioData.nodes || {}).length,
            has_custom_topology: scenarioData.nodes && Object.keys(scenarioData.nodes).length > 0
        });

        scenariosList[actual_scenario] = scenarioData;
        sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
        console.log('replaceScenario: Scenario saved successfully');
    }

    function updateScenariosPosition(isEmptyScenario = false) {
        const container = document.getElementById("scenarios-position");
        if (!container) return;

        // Clear existing content
        container.innerHTML = '';

        if (isEmptyScenario) {
            container.innerHTML = '<span style="margin: 0 10px;">No scenarios</span>';
            return;
        }

        // Create a single span for all scenarios
        const span = document.createElement("span");
        span.style.margin = "0 10px";

        // Create the scenario indicators
        const indicators = scenariosList.map((_, index) =>
            index === actual_scenario ? `●` : `○`
        ).join(' ');

        span.textContent = indicators;
        container.appendChild(span);
    }

    function clearFields() {
        // Mark that we're clearing/loading to prevent auto-save
        isLoadingScenario = true;

        // Reset form fields to default values
        document.getElementById("scenario-title").value = "";
        document.getElementById("scenario-description").value = "";
        document.getElementById("docker-radio").checked = true;
        document.getElementById("federationArchitecture").value = "DFL";
        document.getElementById("rounds").value = "10";

        // Reset topology configuration
        document.getElementById("predefined-topology-btn").checked = true;
        document.getElementById("custom-topology-btn").checked = false;
        document.getElementById("predefined-topology").style.display = "block";
        document.getElementById("predefined-topology-select").value = "Fully";
        document.getElementById("predefined-topology-nodes").value = "3";
        document.getElementById("random-probability").value = "0.5";

        document.getElementById("datasetSelect").value = "MNIST";
        document.getElementById("iidSelect").value = "false";
        document.getElementById("partitionSelect").value = "dirichlet";
        document.getElementById("partitionParameter").value = "0.5";
        document.getElementById("removeClassesCount").value = "0";
        document.getElementById("modelSelect").value = "MLP";
        document.getElementById("aggregationSelect").value = "FedAvg";
        document.getElementById("loggingLevel").value = "false";
        document.getElementById("reportingSwitch").checked = true;
        document.getElementById("epochs").value = "1";

        // Reset modules
        if (window.TopologyManager) {
            window.TopologyManager.generatePredefinedTopology();
        }
        if (window.AttackManager) {
            window.AttackManager.resetAttackConfig();
        }
        if (window.MobilityManager) {
            window.MobilityManager.resetMobilityConfig();
        }
        if (window.ReputationManager) {
            window.ReputationManager.resetReputationConfig();
        }
        if (window.SaManager) {
            window.SaManager.resetSaConfig();
        }

        // Trigger necessary events
        document.getElementById("federationArchitecture").dispatchEvent(new Event('change'));
        document.getElementById("datasetSelect").dispatchEvent(new Event('change'));
        document.getElementById("iidSelect").dispatchEvent(new Event('change'));

        // Set model back to MLP after dataset change has updated options
        setTimeout(() => {
            document.getElementById("modelSelect").value = "MLP";
            // Mark loading as complete after all async operations
            isLoadingScenario = false;
        }, 150);
    }

    function setPhysicalIPs(ipList = []) {
        physical_ips = [...ipList];
    }

    function setActualScenario(index) {
        console.log('setActualScenario: Changing from', actual_scenario, 'to', index);

        // Mark as navigating to prevent auto-save conflicts
        isNavigating = true;

        actual_scenario = index;
        if (scenariosList[index]) {
            // Clear the current graph
            window.TopologyManager.clearGraph();

            // Load new scenario data
            loadScenario(scenariosList[index]);

            // If physical deployment, set physical IPs
            if (scenariosList[index].deployment === 'physical' && scenariosList[index].physical_ips) {
                window.TopologyManager.setPhysicalIPs(scenariosList[index].physical_ips);
            }
        }

        // Clear navigation flag after a delay to allow all async operations to complete
        setTimeout(() => {
            isNavigating = false;
            console.log('setActualScenario: Navigation completed, auto-save re-enabled');
        }, 200);
    }

    // Function specifically for navigation that handles proper saving/loading sequence
    function navigateToScenario(direction) {
        console.log('navigateToScenario: Direction:', direction);

        // Save current scenario before navigating
        if (scenariosList.length > 0) {
            console.log('navigateToScenario: Saving current scenario before navigation');
            replaceScenario();
        }

        // Calculate new index
        const newIndex = direction === 'prev' ? actual_scenario - 1 : actual_scenario + 1;

        // Navigate to new scenario
        setActualScenario(newIndex);
    }

    return {
        saveScenario,
        deleteScenario,
        replaceScenario,
        collectScenarioData,
        loadScenario,
        clearFields,
        updateScenariosPosition,
        initializeScenarios,
        getScenariosList: () => scenariosList,
        getActualScenario: () => actual_scenario,
        setActualScenario,
        navigateToScenario,  // New function for proper navigation
        setScenariosList: (list) => {
            scenariosList = list;
            actual_scenario = 0;
            sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
            updateScenariosPosition(list.length === 0);

            if (list.length > 0) {
                loadScenario(list[0]);
            } else {
                clearFields();
            }
        },
        setPhysicalIPs
    };
})();

export default ScenarioManager;
