// Scenario Management Module
const ScenarioManager = (function() {
    let scenariosList = [];
    let actual_scenario = 0;

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
            model: document.getElementById("modelSelect").value,
            agg_algorithm: document.getElementById("aggregationSelect").value,
            logginglevel: document.getElementById("loggingLevel").value === "true",
            report_status_data_queue: document.getElementById("reportingSwitch").checked,
            epochs: parseInt(document.getElementById("epochs").value),
            attack_params: attackConfig,
            with_reputation: window.ReputationManager.getReputationConfig().with_reputation || false,
            reputation_metrics: window.ReputationManager.getReputationConfig().reputation_metrics || [],
            initial_reputation: window.ReputationManager.getReputationConfig().initial_reputation || 1.0,
            weighting_factor: window.ReputationManager.getReputationConfig().weighting_factor || "static",
            weight_model_arrival_latency: window.ReputationManager.getReputationConfig().weight_model_arrival_latency || 0.25,
            weight_model_similarity: window.ReputationManager.getReputationConfig().weight_model_similarity || 0.25,
            weight_num_messages: window.ReputationManager.getReputationConfig().weight_num_messages || 0.25,
            weight_fraction_params_changed: window.ReputationManager.getReputationConfig().weight_fraction_params_changed || 0.25,
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
            //with_sa : window.SaManager.getSaConfig().with_sa || false,
            with_sa: window.MobilityManager.getMobilityConfig().enabled || false,
            //strict_topology: window.SaManager.getSaConfig().strict_topology || false,
            strict_topology: false,
            //sad_candidate_selector: window.SaManager.getSaConfig().sad_candidate_selector.value || "Distance",
            sad_candidate_selector: "Distance",
            //sad_model_handler:  window.SaManager.getSaConfig().sad_model_handler.value || "std",
            sad_model_handler: "std",
            // sar_arbitration_policy: window.SaManager.getSaConfig().sar_arbitration_policy.value || "sap",
            sar_arbitration_policy: "sap",
            //sar_neighbor_policy: window.SaManager.getSaConfig().sar_neighbor_policy.value || "Distance",
            sar_neighbor_policy: "Distance",
            random_topology_probability: document.getElementById("random-probability").value || 0.5,
            network_subnet: "172.20.0.0/16",
            network_gateway: "172.20.0.1",
            additional_participants: window.MobilityManager.getMobilityConfig().additionalParticipants || [],
            schema_additional_participants: document.getElementById("schemaAdditionalParticipantsSelect").value || "random",
            accelerator: "cpu",
            gpu_id: []
        };
    }

    function loadScenarioData(scenario) {
        if (!scenario) return;

        // Load basic fields
        document.getElementById("scenario-title").value = scenario.scenario_title || "";
        document.getElementById("scenario-description").value = scenario.scenario_description || "";

        // Load deployment
        const deploymentRadio = document.querySelector(`input[name="deploymentRadioOptions"][value="${scenario.deployment}"]`);
        if (deploymentRadio) deploymentRadio.checked = true;

        // Load architecture and rounds
        document.getElementById("federationArchitecture").value = scenario.federation;
        document.getElementById("rounds").value = scenario.rounds;

        // Load topology
        if (scenario.nodes && scenario.nodes_graph) {
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
            window.TopologyManager.generatePredefinedTopology();
        }

        // Load dataset settings
        document.getElementById("datasetSelect").value = scenario.dataset;
        document.getElementById("iidSelect").value = scenario.iid ? "true" : "false";
        document.getElementById("partitionSelect").value = scenario.partition_selection;
        document.getElementById("partitionParameter").value = scenario.partition_parameter;

        // Load model and aggregation
        document.getElementById("modelSelect").value = scenario.model;
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
        if (scenario.with_reputation) {
            window.ReputationManager.setReputationConfig({
                with_reputation: scenario.with_reputation,
                reputation_metrics: scenario.reputation_metrics,
                initial_reputation: scenario.initial_reputation,
                weighting_factor: scenario.weighting_factor,
                weight_model_arrival_latency: scenario.weight_model_arrival_latency,
                weight_model_similarity: scenario.weight_model_similarity,
                weight_num_messages: scenario.weight_num_messages,
                weight_fraction_params_changed: scenario.weight_fraction_params_changed
            });
        }
        if (scenario.with_sa) {
            window.SaManager.setSaConfig({
                with_sa: scenario.with_sa,
                strict_topology: scenario.strict_topology,
                sad_candidate_selector: scenario.sad_candidate_selector,
                sad_model_handler: scenario.sad_model_handler,
                sar_arbitration_policy: scenario.sar_arbitration_policy,
                sar_neighbor_policy: scenario.sar_neighbor_policy
            });
        }

        // Trigger necessary events
        document.getElementById("federationArchitecture").dispatchEvent(new Event('change'));
        document.getElementById("datasetSelect").dispatchEvent(new Event('change'));
        document.getElementById("iidSelect").dispatchEvent(new Event('change'));
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
            loadScenarioData(scenariosList[actual_scenario]);
        } else {
            clearFields();
        }

        sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
        updateScenariosPosition(scenariosList.length === 0);
    }

    function replaceScenario() {
        if (actual_scenario < 0 || actual_scenario >= scenariosList.length) return;

        const scenarioData = collectScenarioData();
        scenariosList[actual_scenario] = scenarioData;
        sessionStorage.setItem("ScenarioList", JSON.stringify(scenariosList));
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
        // Reset form fields to default values
        document.getElementById("scenario-title").value = "";
        document.getElementById("scenario-description").value = "";
        document.getElementById("docker-radio").checked = true;
        document.getElementById("federationArchitecture").value = "DFL";
        document.getElementById("rounds").value = "10";
        document.getElementById("custom-topology-btn").checked = true;
        document.getElementById("predefined-topology").style.display = "none";
        document.getElementById("datasetSelect").value = "MNIST";
        document.getElementById("iidSelect").value = "false";
        document.getElementById("partitionSelect").value = "dirichlet";
        document.getElementById("partitionParameter").value = "0.5";
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
    }

    return {
        saveScenario,
        deleteScenario,
        replaceScenario,
        loadScenarioData,
        clearFields,
        updateScenariosPosition,
        initializeScenarios,
        getScenariosList: () => scenariosList,
        getActualScenario: () => actual_scenario,
        setActualScenario: (index) => {
            actual_scenario = index;
            if (scenariosList[index]) {
                loadScenarioData(scenariosList[index]);
            }
        },
        setScenariosList: (list) => {
            scenariosList = list;
            if (list.length > 0) {
                actual_scenario = 0;
                loadScenarioData(list[0]);
            }
        }
    };
})();

export default ScenarioManager;
