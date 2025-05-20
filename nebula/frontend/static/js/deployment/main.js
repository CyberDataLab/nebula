// Main Deployment Module
import ScenarioManager from './scenario.js';
import TopologyManager from './topology.js';
import AttackManager from './attack.js';
import MobilityManager from './mobility.js';
import ReputationManager from './reputation.js';
import GraphSettings from './graph-settings.js';
import Utils from './utils.js';

const DeploymentManager = (function() {
    function initialize() {
        // First initialize all modules
        initializeModules();
        
        // Then initialize event listeners and UI controls
        initializeEventListeners();
        setupDeploymentButtons();
        initializeSelectElements();
        
        // Finally initialize scenarios after all modules are ready
        ScenarioManager.initializeScenarios();
    }

    function initializeModules() {
        // Initialize all sub-modules
        TopologyManager.initializeGraph('3d-graph', getGraphWidth(), getGraphHeight());
        AttackManager.initializeEventListeners();
        MobilityManager.initializeMobility();
        ReputationManager.initializeReputationSystem();
        GraphSettings.initializeDistanceControls();
        
        // Make modules globally available
        window.ScenarioManager = ScenarioManager;
        window.TopologyManager = TopologyManager;
        window.AttackManager = AttackManager;
        window.MobilityManager = MobilityManager;
        window.ReputationManager = ReputationManager;
        window.GraphSettings = GraphSettings;
        window.DeploymentManager = DeploymentManager;
        window.Utils = Utils;
    }

    function getGraphWidth() {
        return document.getElementById('3d-graph').offsetWidth;
    }

    function getGraphHeight() {
        return document.getElementById('3d-graph').offsetHeight;
    }

    function initializeEventListeners() {
        window.addEventListener("resize", handleResize);
        window.addEventListener("click", handleOutsideClick);
        setupDatasetListeners();
        setupInputValidation();
    }

    function handleResize() {
        TopologyManager.updateGraph();
    }

    function handleOutsideClick(event) {
        if (!event.target.matches('.dropdown-item')) {
            const dropdowns = document.getElementsByClassName("dropdown-menu");
            Array.from(dropdowns).forEach(dropdown => {
                if (dropdown.style.display === "block") {
                    dropdown.style.display = "none";
                }
            });
        }
    }

    function setupDeploymentButtons() {
        const runBtn = document.getElementById("run-btn");
        if (runBtn) {
            runBtn.addEventListener("click", (event) => {
                event.stopPropagation();
                if (!validateScenario()) {
                    return;
                }
                window.UIControls.handleDeployment();
            });
        }
    }

    function validateScenario() {
        const physicalDevicesRadio = document.getElementById('physical-devices-radio');
        if (physicalDevicesRadio && physicalDevicesRadio.checked) {
            if (!window.lastPhysicalDevicesAlert || Date.now() - window.lastPhysicalDevicesAlert > 1000) {
                Utils.showAlert('danger', 'Physical devices deployment is not supported in this version');
                window.lastPhysicalDevicesAlert = Date.now();
            }
            return false;
        }

        // Validate topology
        if (!TopologyManager.getData().nodes.length) {
            Utils.showAlert('error', 'Please create a topology with at least one node');
            return false;
        }

        // Validate start node
        if (!document.querySelector(".participant-started")) {
            Utils.showAlert('error', 'Please select one "start" participant for the scenario');
            return false;
        }

        return true;
    }

    function setupDatasetListeners() {
        const datasetSelect = document.getElementById("datasetSelect");
        if (datasetSelect) {
            datasetSelect.addEventListener("change", () => {
                // Update model options based on selected dataset
                updateModelOptions(datasetSelect.value);
            });
        }
    }

    function initializeSelectElements() {
        // Initialize dataset options
        populateDatasetOptions();

        // Initialize topology options
        const topologySelect = document.getElementById("predefined-topology-select");
        if (topologySelect) {
            const topologies = ['Fully', 'Ring', 'Star', 'Random'];
            topologies.forEach(topology => {
                if (!topologySelect.querySelector(`option[value="${topology}"]`)) {
                    const option = document.createElement("option");
                    option.value = topology;
                    option.textContent = topology;
                    topologySelect.appendChild(option);
                }
            });
            topologySelect.value = 'Fully';
        }

        // Initialize IID options
        const iidSelect = document.getElementById("iidSelect");
        if (iidSelect) {
            const iidOptions = [
                { value: 'true', text: 'IID' },
                { value: 'false', text: 'Non-IID' }
            ];
            iidOptions.forEach(opt => {
                if (!iidSelect.querySelector(`option[value="${opt.value}"]`)) {
                    const option = document.createElement("option");
                    option.value = opt.value;
                    option.textContent = opt.text;
                    iidSelect.appendChild(option);
                }
            });
            iidSelect.value = 'false';
        }

        // Initialize partition options
        const partitionSelect = document.getElementById("partitionSelect");
        if (partitionSelect) {
            const partitionOptions = [
                { value: 'dirichlet', text: 'Dirichlet' },
                { value: 'percent', text: 'Percentage' },
                { value: 'balancediid', text: 'Balanced IID' },
                { value: 'unbalancediid', text: 'Unbalanced IID' }
            ];
            partitionOptions.forEach(opt => {
                if (!partitionSelect.querySelector(`option[value="${opt.value}"]`)) {
                    const option = document.createElement("option");
                    option.value = opt.value;
                    option.textContent = opt.text;
                    option.disabled = opt.value === 'balancediid' || opt.value === 'unbalancediid';
                    option.style.display = opt.value === 'balancediid' || opt.value === 'unbalancediid' ? 'none' : 'block';
                    partitionSelect.appendChild(option);
                }
            });
            partitionSelect.value = 'dirichlet';
        }

        // Initialize logging level options
        const loggingLevel = document.getElementById("loggingLevel");
        if (loggingLevel) {
            const loggingOptions = [
                { value: 'false', text: 'Only alerts' },
                { value: 'true', text: 'Alerts and logs' }
            ];
            loggingOptions.forEach(opt => {
                if (!loggingLevel.querySelector(`option[value="${opt.value}"]`)) {
                    const option = document.createElement("option");
                    option.value = opt.value;
                    option.textContent = opt.text;
                    loggingLevel.appendChild(option);
                }
            });
            loggingLevel.value = 'true';
        }
    }

    function populateDatasetOptions() {
        const datasetSelect = document.getElementById("datasetSelect");
        if (!datasetSelect) return;

        // Clear existing options
        datasetSelect.innerHTML = "";

        // Add dataset options
        const datasets = ['MNIST', 'FashionMNIST', 'EMNIST', 'CIFAR10', 'CIFAR100'];
        datasets.forEach(dataset => {
            const option = document.createElement("option");
            option.value = dataset;
            option.textContent = dataset;
            datasetSelect.appendChild(option);
        });

        // Set default value and trigger change event
        datasetSelect.value = 'MNIST';
        datasetSelect.dispatchEvent(new Event('change'));
    }

    function updateModelOptions(dataset) {
        const modelSelect = document.getElementById("modelSelect");
        if (!modelSelect) return;

        // Clear existing options
        modelSelect.innerHTML = "";

        // Add appropriate models based on dataset
        const models = getModelsForDataset(dataset);
        models.forEach(model => {
            const option = document.createElement("option");
            option.value = model;
            option.textContent = model;
            modelSelect.appendChild(option);
        });
    }

    function getModelsForDataset(dataset) {
        // Return appropriate models based on dataset
        switch(dataset.toLowerCase()) {
            case 'mnist':
            case 'fashionmnist':
            case 'emnist':
                return ['MLP', 'CNN'];
            case 'cifar10':
                return ['CNN', 'ResNet9', 'fastermobilenet', 'simplemobilenet', 'CNNv2', 'CNNv3'];
            case 'cifar100':
                return ['CNN'];
            default:
                return ['MLP', 'CNN'];
        }
    }

    function setupInputValidation() {
        const numericInputs = document.querySelectorAll('input[type="number"]');
        numericInputs.forEach(input => {
            if(input.hasAttribute('min')) {
                input.addEventListener('input', () => Utils.greaterThan0(input));
            }
            if(input.hasAttribute('min') && input.hasAttribute('max')) {
                input.addEventListener('input', () => Utils.isInRange(input, 
                    parseInt(input.getAttribute('min')), 
                    parseInt(input.getAttribute('max'))));
            }
        });
    }

    return {
        initialize,
        validateScenario
    };
})();

export default DeploymentManager; 