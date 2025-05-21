// UI Controls Module
const UIControls = (function() {
    function initializeUIControls() {
        setupModeButton();
        setupPartitionControls();
        setupMethodTip();
        setupReputationControls();
        setupActionButtons();
        setupDeploymentButtons();
        setupParticipantDisplay();
        setupParticipantModal();
        setupConfigButtons();
        // Initialize help icons
        window.HelpContent.initializePopovers();
    }

    function setupModeButton() {
        const modeBtn = document.getElementById('mode-btn');
        const expertContainer = document.getElementById('expert-container');
        const loggingLevel = document.getElementById('loggingLevel');

        if (modeBtn) {
            modeBtn.addEventListener('click', function() {
                const isAdvancedMode = modeBtn.innerHTML.trim() === "Advanced mode";

                if (isAdvancedMode) {
                    // Switch to advanced mode
                    modeBtn.innerHTML = "User mode";
                    modeBtn.classList.remove("btn-dark");
                    modeBtn.classList.add("btn-light");
                    expertContainer.style.display = "block";
                    expertContainer.style.visibility = "visible";
                    expertContainer.style.opacity = "1";
                    expertContainer.style.transition = "all 0.5s ease-in-out";
                    loggingLevel.value = "true";
                } else {
                    // Switch back to user mode
                    resetModeBtn();
                }
            });
        }
    }

    function resetModeBtn() {
        const modeBtn = document.getElementById('mode-btn');
        const expertContainer = document.getElementById('expert-container');
        const loggingLevel = document.getElementById('loggingLevel');

        modeBtn.innerHTML = "Advanced mode";
        modeBtn.classList.remove("btn-light");
        modeBtn.classList.add("btn-dark");
        expertContainer.style.display = "none";
        expertContainer.style.visibility = "hidden";
        expertContainer.style.opacity = "0";
        expertContainer.style.transition = "all 0.5s ease-in-out";
        loggingLevel.value = "false";
    }

    function setupPartitionControls() {
        const iidSelect = document.getElementById("iidSelect");
        const partitionSelect = document.getElementById("partitionSelect");
        const partitionBlock = document.getElementById("partitionBlock");
        const partitionParameter = document.getElementById("partitionParameter");

        iidSelect.addEventListener("change", function() {
            if (iidSelect.value === "false") {
                // Set up for non-IID
                partitionSelect.options[0].selected = true;
                partitionSelect.options[2].selected = false;
                partitionSelect.options[0].disabled = false;
                partitionSelect.options[1].disabled = false;
                partitionSelect.options[2].disabled = true;
                partitionSelect.options[3].disabled = true;

                partitionSelect.options[0].style.display = "block";
                partitionSelect.options[1].style.display = "block";
                partitionSelect.options[2].style.display = "none";
                partitionSelect.options[3].style.display = "none";
                partitionBlock.style.display = "block";
            } else {
                // Set up for IID
                partitionSelect.options[0].selected = false;
                partitionSelect.options[2].selected = true;
                partitionSelect.options[0].disabled = true;
                partitionSelect.options[1].disabled = true;
                partitionSelect.options[2].disabled = false;
                partitionSelect.options[3].disabled = false;

                partitionSelect.options[0].style.display = "none";
                partitionSelect.options[1].style.display = "none";
                partitionSelect.options[2].style.display = "block";
                partitionSelect.options[3].style.display = "block";
                partitionBlock.style.display = "none";
            }
        });

        partitionSelect.addEventListener("change", function() {
            switch(partitionSelect.value) {
                case "balancediid":
                    partitionBlock.style.display = "none";
                    partitionParameter.value = "0.0";
                    break;
                case "unbalancediid":
                    partitionBlock.style.display = "block";
                    partitionParameter.value = "2";
                    partitionParameter.step = "0.1";
                    partitionParameter.min = "1";
                    break;
                case "dirichlet":
                    partitionBlock.style.display = "block";
                    partitionParameter.value = "0.5";
                    partitionParameter.step = "0.1";
                    partitionParameter.min = "0.1";
                    break;
                case "percentage":
                    partitionBlock.style.display = "block";
                    partitionParameter.value = "50";
                    partitionParameter.step = "1";
                    partitionParameter.min = "10";
                    partitionParameter.max = "100";
                    break;
            }
        });
    }

    function setupMethodTip() {
        const methodtip = document.getElementById('methodtip');
        const methodtipImage = document.getElementById('methodtipImage');
        const partitionSelect = document.getElementById('partitionSelect');

        methodtip.addEventListener('mouseover', function() {
            const imageMap = {
                "dirichlet": "dirichlet_noniid.png",
                "percent": "percentage.png",
                "balancediid": "balancediid.png",
                "unbalancediid": "unbalanceiid.png"
            };

            const imageName = imageMap[partitionSelect.value];
            if (imageName) {
                methodtipImage.src = `/platform/static/images/${imageName}`;
                methodtipImage.style.display = "block";
            }
        });

        methodtip.addEventListener('mouseout', function() {
            methodtipImage.style.display = "none";
        });
    }

    function setupReputationControls() {
        const reputationSwitch = document.getElementById("reputationSwitch");
        const initialReputation = document.getElementById("initial-reputation");
        const weightingFactor = document.getElementById("weighting-factor");
        const weightInputs = document.querySelectorAll(".weight-input");

        reputationSwitch.addEventListener("change", function() {
            const elements = ["reputation-metrics", "reputation-settings", "weighting-settings"];
            elements.forEach(id => {
                document.getElementById(id).style.display = this.checked ? "block" : "none";
            });
        });

        initialReputation.addEventListener("blur", function() {
            const min = parseFloat(this.min);
            const max = parseFloat(this.max);
            const value = parseFloat(this.value);

            if (value < min) this.value = min;
            else if (value > max) this.value = max;
        });

        weightingFactor.addEventListener("change", function() {
            const showWeights = this.value === "static";
            weightInputs.forEach(input => {
                input.style.display = showWeights ? "inline-block" : "none";
            });
        });

        weightInputs.forEach(input => {
            input.addEventListener("input", validateWeights);
        });
    }

    function validateWeights() {
        let totalWeight = 0;
        document.querySelectorAll(".weight-input").forEach(input => {
            const checkbox = input.previousElementSibling.previousElementSibling;
            if (checkbox.checked && input.style.display !== "none" && input.value) {
                totalWeight += parseFloat(input.value);
            }
        });
        document.getElementById("weight-warning").style.display = totalWeight > 1 ? "block" : "none";
    }

    function setupActionButtons() {
        // Add button
        const addBtn = document.getElementById('add-btn');
        if (addBtn) {
            addBtn.addEventListener('click', function() {
                window.ScenarioManager.saveScenario();
                updateButtonVisibility();
            });
        }

        // Delete button
        const delBtn = document.getElementById('del-btn');
        if (delBtn) {
            delBtn.addEventListener('click', function() {
                window.ScenarioManager.deleteScenario();
                if (window.ScenarioManager.getScenariosList().length < 1) {
                    window.ScenarioManager.clearFields();
                    window.ScenarioManager.updateScenariosPosition(true);
                    updateButtonVisibility(true);
                } else {
                    window.ScenarioManager.updateScenariosPosition();
                    updateButtonVisibility();
                }
            });
        }

        // Previous button
        const prevBtn = document.getElementById('prev-btn');
        if (prevBtn) {
            prevBtn.addEventListener('click', function() {
                window.ScenarioManager.replaceScenario();
                window.ScenarioManager.setActualScenario(window.ScenarioManager.getActualScenario() - 1);
                window.ScenarioManager.updateScenariosPosition();
                updateButtonVisibility();
            });
        }

        // Next button
        const nextBtn = document.getElementById('next-btn');
        if (nextBtn) {
            nextBtn.addEventListener('click', function() {
                window.ScenarioManager.replaceScenario();
                window.ScenarioManager.setActualScenario(window.ScenarioManager.getActualScenario() + 1);
                window.ScenarioManager.updateScenariosPosition();
                updateButtonVisibility();
            });
        }
    }

    function updateButtonVisibility(isEmptyScenario = false) {
        const prevBtn = document.getElementById("prev-btn");
        const nextBtn = document.getElementById("next-btn");
        const addBtn = document.getElementById("add-btn");
        const delBtn = document.getElementById("del-btn");
        const runBtn = document.getElementById("run-btn");

        if (isEmptyScenario) {
            prevBtn.style.display = "none";
            nextBtn.style.display = "none";
            delBtn.style.display = "none";
            runBtn.disabled = true;
            addBtn.style.display = "inline-block";
            return;
        }

        const scenarioCount = window.ScenarioManager.getScenariosList().length;
        const currentScenario = window.ScenarioManager.getActualScenario();

        prevBtn.style.display = currentScenario > 0 ? "inline-block" : "none";
        nextBtn.style.display = currentScenario < scenarioCount - 1 ? "inline-block" : "none";
        addBtn.style.display = currentScenario === scenarioCount - 1 ? "inline-block" : "none";
        delBtn.style.display = "inline-block";
        runBtn.disabled = false;
    }

    function setupDeploymentButtons() {
        const runBtn = document.getElementById('run-btn');
        if (runBtn) {
            runBtn.addEventListener('click', handleDeployment);
        }
    }

    async function handleDeployment() {
        // First check validation
        if (!window.DeploymentManager.validateScenario()) {
            return;
        }

        const confirmModal = document.getElementById('confirm-modal');
        const confirmModalBody = document.getElementById('confirm-modal-body');
        const yesButton = document.getElementById("yes-button");

        if (!document.querySelector(".participant-started")) {
            confirmModalBody.innerHTML = 'Please select one "start" participant for the scenario';
            yesButton.disabled = true;
            const modal = new bootstrap.Modal(confirmModal);
            modal.show();
            return;
        }

        const deploymentOption = document.querySelector('input[name="deploymentRadioOptions"]:checked');
        confirmModalBody.innerHTML = `Are you sure you want to run the scenario?
            <br><p class="badge text-bg-warning">The scenario will be deployed using the selected deployment option: ${deploymentOption.value}</p>
            <br><p class="badge text-bg-danger">Warning: you will stop the running scenario and start a new one</p>`;
        yesButton.disabled = false;

        const modal = new bootstrap.Modal(confirmModal);

        confirmModal.addEventListener('hidden.bs.modal', function () {
            cleanupModal(confirmModal);
        });

        modal.show();

        yesButton.onclick = async () => {
            // If no scenarios exist, save the current one first
            if (window.ScenarioManager.getScenariosList().length < 1) {
                window.ScenarioManager.saveScenario();
            } else {
                window.ScenarioManager.replaceScenario();
            }

            // Ensure all scenarios have a title
            window.ScenarioManager.getScenariosList().forEach((scenario, index) => {
                if (!scenario.scenario_title) {
                    scenario.scenario_title = "empty";
                }
                if (!scenario.scenario_description) {
                    scenario.scenario_description = "empty";
                }
            });

            modal.hide();
            document.querySelector(".overlay").style.display = "block";
            document.getElementById("spinner").style.display = "block";

            try {
                const response = await fetch("/platform/dashboard/deployment/run", {
                    method: "POST",
                    headers: {
                        'Content-Type': 'application/json'
                    },
                    body: JSON.stringify(window.ScenarioManager.getScenariosList())
                });

                if (response.redirected) {
                    window.location.href = response.url;
                } else if (!response.ok) {
                    hideLoadingIndicators();
                    handleDeploymentError(response.status);
                }
            } catch (error) {
                console.error('Error:', error);
                hideLoadingIndicators();
                handleDeploymentError(500, error);
            }
        };
    }

    function handleDeploymentError(status, error = null) {
        hideLoadingIndicators();
        let errorMessage;

        switch(status) {
            case 401:
                errorMessage = "You are not authorized to run a scenario. Please log in.";
                break;
            case 503:
                errorMessage = "Not enough resources to run a scenario. Please try again later.";
                break;
            default:
                errorMessage = "An unexpected error occurred. See console for more details.";
        }
        if (error) {
            console.error('Error:', error);
        }
        showErrorModal(errorMessage);
    }

    function showErrorModal(message) {
        const infoModal = document.getElementById('info-modal');
        const infoModalBody = document.getElementById('info-modal-body');
        infoModalBody.innerHTML = message;
        const modal = new bootstrap.Modal(infoModal);

        // Add event listener for when modal is hidden
        infoModal.addEventListener('hidden.bs.modal', function () {
            cleanupModal(infoModal);
        });

        modal.show();
    }

    function cleanupModal(modal) {
        if (!document.getElementById("spinner").style.display === "block") {
            document.querySelector(".overlay").style.display = "none";
        }
        // Remove the modal backdrop
        const backdrop = document.querySelector('.modal-backdrop');
        if (backdrop) {
            backdrop.remove();
        }
        // Remove the modal-open class from body
        document.body.classList.remove('modal-open');
        document.body.style.overflow = '';
        document.body.style.paddingRight = '';
    }

    function hideLoadingIndicators() {
        document.querySelector(".overlay").style.display = "none";
        document.getElementById("spinner").style.display = "none";
    }

    function setupParticipantDisplay() {
        // Initial update of participants
        updateParticipantDisplay();

        // Listen for graph data changes
        document.addEventListener('graphDataUpdated', updateParticipantDisplay);
    }

    function updateParticipantDisplay() {
        const participantItems = document.getElementById("participant-items");
        if (!participantItems) return;

        const graph = window.TopologyManager.getGraph();
        if (!graph) return;

        const nodes = graph.graphData().nodes;
        const numberOfNodes = nodes.length;

        // Update the info-participants number
        const infoParticipantsNumber = document.getElementById("info-participants-number");
        if (infoParticipantsNumber) {
            infoParticipantsNumber.innerHTML = numberOfNodes;
        }

        // Clear existing participants
        participantItems.innerHTML = "";

        // Create participant items
        nodes.forEach((node, i) => {
            const participantItem = createParticipantItem(node, i);
            participantItems.appendChild(participantItem);
        });

        // If there is no participant-started, add the class to the first participant
        if (document.getElementsByClassName("participant-started").length === 0 && nodes.length > 0) {
            const firstStartBtn = document.getElementById("participant-0-start-btn");
            if (firstStartBtn) {
                firstStartBtn.classList.add("participant-started");
                firstStartBtn.title = `Participant 0 (start node)`;
                nodes[0].start = true;
            }
        }
    }

    function createParticipantItem(node, index) {
        const participantItem = document.createElement("div");
        participantItem.classList.add("col-md-2");
        participantItem.classList.add("participant-item");

        // Create participant image
        const participantImg = document.createElement("img");
        participantImg.id = `participant-img-${index}`;
        participantImg.setAttribute("data-id", index.toString());
        participantImg.src = "/platform/static/images/device.png";
        participantImg.width = 50;
        participantImg.height = 50;
        participantImg.style.marginRight = "10px";

        // Create label
        const label = document.createElement("label");
        label.setAttribute("for", `participant-${index}`);
        label.setAttribute("data-id", index.toString());
        label.innerHTML = `Participant ${index}`;
        label.style.marginRight = "10px";

        // Create info button
        const infoBtn = createInfoButton(node, index);

        // Create start button
        const startBtn = createStartButton(node, index);

        // Add all elements to participant item
        participantItem.appendChild(participantImg);
        participantItem.appendChild(label);
        participantItem.appendChild(infoBtn);
        participantItem.appendChild(startBtn);

        return participantItem;
    }

    function createInfoButton(node, index) {
        const infoBtn = document.createElement("button");
        infoBtn.id = `participant-${index}-btn`;
        infoBtn.setAttribute("data-id", index.toString());
        infoBtn.type = "button";
        infoBtn.classList.add("btn", "btn-info-participant");
        infoBtn.innerHTML = "Details";
        infoBtn.style.border = "none";
        infoBtn.style.cursor = "pointer";

        infoBtn.addEventListener("click", () => {
            showParticipantDetails(node, index);
        });

        return infoBtn;
    }

    function createStartButton(node, index) {
        const startBtn = document.createElement("button");
        startBtn.id = `participant-${index}-start-btn`;
        startBtn.setAttribute("data-id", index.toString());
        startBtn.type = "button";
        startBtn.classList.add("btn");
        startBtn.innerHTML = "Start";
        startBtn.style.marginLeft = "10px";
        startBtn.style.border = "none";
        startBtn.style.cursor = "pointer";

        if (node.start) {
            startBtn.classList.add("participant-started");
            startBtn.title = `Participant ${index} (start node)`;
        } else {
            startBtn.classList.add("participant-not-started");
            startBtn.title = `Participant ${index} (not start node)`;
        }

        startBtn.addEventListener("click", () => {
            handleStartButtonClick(startBtn, node, index);
        });

        return startBtn;
    }

    function showParticipantDetails(node, index) {
        const modalTitle = document.getElementById("participant-modal-title");
        const modalContent = document.getElementById("participant-modal-content");

        modalTitle.innerHTML = `Participant ${index}`;
        modalContent.innerHTML = "";

        // Add additional info
        modalContent.innerHTML += `<b>Neighbors:</b> ${node.neighbors.length}<br><b>Role:</b> ${node.role}<br><b>Start:</b> ${node.start}`;

        // Show modal
        $('#participant-modal').modal('show');
    }

    function handleStartButtonClick(startBtn, node, index) {
        const currentStarted = document.querySelector(".participant-started");
        if (currentStarted) {
            const graph = window.TopologyManager.getGraph();
            if (!graph) return;

            const nodes = graph.graphData().nodes;
            const currentStartedNode = nodes[currentStarted.getAttribute("data-id")];
            if (currentStartedNode) {
                currentStartedNode.start = false;
                currentStarted.classList.remove("participant-started");
                currentStarted.classList.add("participant-not-started");
                currentStarted.title = `Participant ${currentStarted.getAttribute("data-id")} (not start node)`;
            }
        }

        startBtn.classList.remove("participant-not-started");
        startBtn.classList.add("participant-started");
        startBtn.title = `Participant ${index} (start node)`;
        node.start = true;

        // Update graph data
        const graph = window.TopologyManager.getGraph();
        if (graph) {
            graph.graphData(graph.graphData());
        }
    }

    function setupParticipantModal() {
        const modal = document.getElementById('participant-modal');
        const closeButton = modal.querySelector('.close');

        closeButton.addEventListener('click', () => {
            $(modal).modal('hide');
        });
    }

    function setupConfigButtons() {
        // Save configuration button
        const saveConfigBtn = document.getElementById('save-config-btn');
        if (saveConfigBtn) {
            saveConfigBtn.addEventListener('click', function() {
                const scenarioData = window.ScenarioManager.collectScenarioData();
                const blob = new Blob([JSON.stringify(scenarioData, null, 2)], { type: 'application/json' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `${scenarioData.title || 'scenario'}.json`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
            });
        }

        // Load configuration button
        const loadConfigBtn = document.getElementById('load-config-btn');
        if (loadConfigBtn) {
            loadConfigBtn.addEventListener('click', function() {
                const input = document.createElement('input');
                input.type = 'file';
                input.accept = '.json';
                input.onchange = function(e) {
                    const file = e.target.files[0];
                    if (file) {
                        const reader = new FileReader();
                        reader.onload = function(e) {
                            try {
                                const scenarioData = JSON.parse(e.target.result);
                                window.ScenarioManager.loadScenarioData(scenarioData);
                                window.ScenarioManager.saveScenario();
                                window.ScenarioManager.updateScenariosPosition();
                                updateButtonVisibility();
                            } catch (error) {
                                console.error('Error loading configuration:', error);
                                alert('Error loading configuration file. Please make sure it is a valid JSON file.');
                            }
                        };
                        reader.readAsText(file);
                    }
                };
                input.click();
            });
        }
    }

    return {
        initializeUIControls,
        resetModeBtn,
        updateButtonVisibility,
        updateParticipantDisplay,
        setupParticipantModal,
        handleDeployment
    };
})();

export default UIControls;
