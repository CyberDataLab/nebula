// Topology Management Module

const TopologyManager = (function() {
    let gData = {
        nodes: [],
        links: []
    };
    let Graph = null;
    let selectedNodes = new Set();

    function initializeGraph(containerId, width, height) {
        setupTopologyListeners();
        generatePredefinedTopology();
    }

    function setupTopologyListeners() {
        const topologySelect = document.getElementById('predefined-topology-select');
        const nodesInput = document.getElementById('predefined-topology-nodes');
        const probabilitySelect = document.getElementById('random-probability');
        const randomOptions = document.getElementById('random-topology-options');
        const predefinedTopology = document.getElementById('predefined-topology');
        const customTopologyBtn = document.getElementById('custom-topology-btn');
        const predefinedTopologyBtn = document.getElementById('predefined-topology-btn');

        // Set default topology
        topologySelect.value = 'Fully';
        nodesInput.value = '3';
        predefinedTopologyBtn.checked = true;
        predefinedTopology.style.display = 'block';

        // Add radio button listeners
        customTopologyBtn.addEventListener('change', () => {
            predefinedTopology.style.display = 'none';
        });

        predefinedTopologyBtn.addEventListener('change', () => {
            predefinedTopology.style.display = 'block';
            generatePredefinedTopology();
        });

        document.querySelectorAll('input[name="deploymentRadioOptions"]').forEach(radio => {
            radio.addEventListener('change', () => {
                if (Graph) {
                    Graph.nodeThreeObject(node => createNodeObject(node));
                    Graph.graphData(gData);
                }
            });
        });

        // Add federation architecture change listener
        document.getElementById('federationArchitecture').addEventListener('change', function() {
            const federationType = this.value;
            const topologySelect = document.getElementById('predefined-topology-select');

            if (federationType === 'CFL') {
                // For CFL, only allow Star topology
                topologySelect.value = 'Star';
                topologySelect.disabled = true;
                predefinedTopologyBtn.checked = true;
                predefinedTopology.style.display = 'block';
                customTopologyBtn.disabled = true;
            } else {
                // For DFL and SDFL, allow all topologies
                topologySelect.disabled = false;
                customTopologyBtn.disabled = false;
            }

            generatePredefinedTopology();
        });

        topologySelect.addEventListener('change', () => {
            if (topologySelect.value === 'Random') {
                randomOptions.style.display = 'block';
            } else {
                randomOptions.style.display = 'none';
            }
            generatePredefinedTopology();
        });

        nodesInput.addEventListener('input', () => {
            generatePredefinedTopology();
        });

        probabilitySelect.addEventListener('change', () => {
            if (topologySelect.value === 'Random') {
                generatePredefinedTopology();
            }
        });
    }

    function generatePredefinedTopology() {
        const topologyType = document.getElementById('predefined-topology-select').value;
        const N = parseInt(document.getElementById('predefined-topology-nodes').value) || 3;
        let probability = 0.5; // default value

        if (topologyType === 'Random') {
            const probSelect = document.getElementById('random-probability');
            probability = parseFloat(probSelect.value);
        }

        // Create nodes with roles based on topology type
        gData.nodes = [...Array(N).keys()].map(i => {
            let role;
            switch(topologyType) {
                case 'Fully':
                    role = "aggregator";
                    break;
                case 'Star':
                    role = i === 0 ? "server" : "trainer";
                    break;
                case 'Ring':
                    role = "aggregator";
                    break;
                case 'Random':
                    role = "aggregator";
                    break;
                default:
                    role = i === 0 ? "aggregator" : "trainer";
            }

            return {
                id: i,
                ip: "127.0.0.1",
                port: (45000 + i).toString(),
                role: role,
                malicious: false,
                proxy: false,
                start: (i === 0),
                neighbors: [],
                links: [],
            };
        });

        // Create links based on topology type
        gData.links = [];
        switch(topologyType) {
            case 'Fully':
                for (let i = 0; i < N; i++) {
                    for (let j = i + 1; j < N; j++) {
                        gData.links.push({ source: i, target: j });
                    }
                }
                break;
            case 'Ring':
                for (let i = 0; i < N; i++) {
                    gData.links.push({ source: i, target: (i + 1) % N });
                }
                break;
            case 'Star':
                for (let i = 1; i < N; i++) {
                    gData.links.push({ source: 0, target: i });
                }
                break;
            case 'Random':
                for (let i = 0; i < N; i++) {
                    for (let j = i + 1; j < N; j++) {
                        if (Math.random() < probability) {
                            gData.links.push({ source: i, target: j });
                        }
                    }
                }
                break;
        }

        // After generating topology, assign roles based on federation architecture
        assignRolesByFederationArchitecture();

        // Update graph visualization
        if (Graph) {
            updateGraph();
        } else {
            const containerId = '3d-graph';
            Graph = ForceGraph3D()(document.getElementById(containerId))
                .graphData(gData)
                .nodeThreeObject(createNodeObject)
                .showNavInfo(false)
                .width(document.getElementById(containerId).offsetWidth)
                .height(document.getElementById(containerId).offsetHeight)
                .backgroundColor('#ffffff')
                .nodeLabel(node => `<p style="color: black">ID: ${node.id} | Role: ${node.role} | ${node.malicious ? 'Malicious' : 'Honest'}</p>`)
                .onNodeRightClick(handleNodeRightClick)
                .onNodeClick(handleNodeClick)
                .onBackgroundClick(handleBackgroundClick)
                .onLinkClick(handleLinkClick)
                .linkColor(link => link.color || '#999')
                .linkWidth(2)
                .linkOpacity(0.6)
                .linkDirectionalParticles(2)
                .linkDirectionalParticleWidth(2)
                .linkDirectionalParticleSpeed(0.005)
                .linkCurvature(0.25)
                .linkDirectionalParticleResolution(2)
                .linkDirectionalParticleColor(() => '#ff0000');
        }

        // Update neighbors
        updateNeighbors();
        // Emit event when graph data changes
        emitGraphDataUpdated();
    }

    function updateGraphData(newData) {
        gData = newData;
        Graph.graphData(gData);
        emitGraphDataUpdated();
    }

    function emitGraphDataUpdated() {
        document.dispatchEvent(new CustomEvent('graphDataUpdated'));
    }

    function handleNodeRightClick(node, event) {
        const dropdown = document.getElementById("node-dropdown");
        dropdown.innerHTML = "";
        dropdown.style.display = "block";
        dropdown.style.left = event.clientX + "px";
        dropdown.style.top = event.clientY + "px";
        dropdown.style.position = "absolute";
        dropdown.style.zIndex = "1000";
        dropdown.style.backgroundColor = "white";
        dropdown.style.border = "1px solid black";
        dropdown.style.padding = "10px";
        dropdown.style.borderRadius = "5px";
        dropdown.style.boxShadow = "0 0 10px rgba(0,0,0,0.5)";
        dropdown.setAttribute("data-id", node.id);

        const title = document.createElement("h5");
        title.innerHTML = "Node " + node.id;
        dropdown.appendChild(title);

        createDropdownOptions(dropdown, node);
    }

    function createDropdownOptions(dropdown, node) {
        const options = [
            {
                label: "Add node",
                icon: "fa-plus",
                handler: () => addNode(node),
                condition: () => document.getElementById("federationArchitecture").value !== "CFL"
            },
            {
                label: "Remove node",
                icon: "fa-minus",
                handler: () => removeNode(node),
                condition: () => document.getElementById("federationArchitecture").value !== "CFL"
            },
            {
                label: "Change role",
                icon: "fa-refresh",
                handler: () => changeRole(node),
                condition: () => document.getElementById("federationArchitecture").value !== "CFL"
            },
            {
                label: "Change malicious",
                icon: "fa-exclamation-triangle",
                handler: () => changeMalicious(node),
                condition: () => true
            },
            {
                label: "Change proxy",
                icon: "fa-exchange",
                handler: () => changeProxy(node),
                condition: () => document.getElementById("federationArchitecture").value !== "CFL"
            }
        ];

        options.forEach(option => {
            if (option.condition()) {
                const element = createDropdownElement(option.label, option.icon, option.handler);
                dropdown.appendChild(element);
            }
        });
    }

    function createDropdownElement(label, icon, handler) {
        const element = document.createElement("a");
        element.innerHTML = `<i class="fa ${icon}" aria-hidden="true"></i> ${label}`;
        element.style.display = "block";
        element.style.cursor = "pointer";
        element.style.padding = "5px";
        element.style.borderRadius = "5px";
        element.style.marginBottom = "5px";
        element.classList.add("dropdown-item");
        element.addEventListener("click", handler);
        return element;
    }

    function handleNodeClick(node) {
        if (!selectedNodes.has(node)) {
            selectedNodes.add(node);
        } else {
            selectedNodes.delete(node);
        }

        // Force graph update to show color change
        Graph.nodeThreeObject(node => createNodeObject(node));

        if (selectedNodes.size === 2) {
            const [a, b] = selectedNodes;
            if (document.getElementById("federationArchitecture").value !== "CFL") {
                const link = { source: a, target: b };
                a.neighbors.push(b.id);
                b.neighbors.push(a.id);
                gData.links.push(link);
            }
            selectedNodes.clear();
            // Force another update after clearing selection
            Graph.nodeThreeObject(node => createNodeObject(node));
        }
        updateGraph();
    }

    function handleLinkClick(link) {
        if (document.getElementById("federationArchitecture").value === "CFL") {
            return;
        }

        // Find and remove both directional links
        const source = typeof link.source === 'object' ? link.source.id : link.source;
        const target = typeof link.target === 'object' ? link.target.id : link.target;

        gData.links = gData.links.filter(l => {
            const lSource = typeof l.source === 'object' ? l.source.id : l.source;
            const lTarget = typeof l.target === 'object' ? l.target.id : l.target;
            return !((lSource === source && lTarget === target) || (lSource === target && lTarget === source));
        });

        // Remove from neighbors
        gData.nodes[source].neighbors = gData.nodes[source].neighbors.filter(id => id !== target);
        gData.nodes[target].neighbors = gData.nodes[target].neighbors.filter(id => id !== source);

        updateGraph();
    }

    function addNode(sourceNode) {
        document.getElementById("custom-topology-btn").checked = true;
        document.getElementById("predefined-topology").style.display = "none";

        const newNode = {
            id: gData.nodes.length,
            ip: "127.0.0.1",
            port: "45000",
            role: 'aggregator',
            malicious: false,
            proxy: false,
            start: false,
            neighbors: [sourceNode.id],
            links: []
        };

        sourceNode.neighbors.push(newNode.id);
        gData.nodes.push(newNode);
        gData.links.push({ source: newNode.id, target: sourceNode.id });
        updateGraph();
    }

    function removeNode(node) {
        if (gData.nodes.length <= 1) return;

        document.getElementById("custom-topology-btn").checked = true;
        document.getElementById("predefined-topology").style.display = "none";

        // Remove links connected to this node
        gData.links = gData.links.filter(l =>
            l.source.id !== node.id && l.target.id !== node.id
        );

        // Remove node and update IDs
        gData.nodes = gData.nodes.filter(n => n.id !== node.id);
        gData.nodes.forEach((n, idx) => {
            n.id = idx;
            n.neighbors = n.neighbors.filter(id => id !== node.id)
                                  .map(id => id > node.id ? id - 1 : id);
        });

        updateGraph();
    }

    function changeRole(node) {
        node.role = node.role === 'trainer' ? 'aggregator' : 'trainer';
        updateGraph();
    }

    function changeMalicious(node) {
        document.getElementById("malicious-nodes-select").value = "Manual";
        document.getElementById("malicious-nodes-select").dispatchEvent(new Event('change'));
        node.malicious = !node.malicious;
        // Force complete graph update
        if (Graph) {
            Graph.nodeThreeObject(node => createNodeObject(node));
            Graph.graphData(gData);
        }
        updateGraph();
    }

    function changeProxy(node) {
        node.proxy = !node.proxy;
        // Force complete graph update
        if (Graph) {
            Graph.nodeThreeObject(node => createNodeObject(node));
            Graph.graphData(gData);
        }
        updateGraph();
    }

    function createNodeObject(node) {
        let geometry;
        let main_color;
        const isPhysical = document.getElementById("physical-devices-radio").checked;

        if (isPhysical) {
            const texture = new THREE.TextureLoader().load('/platform/static/images/physical-device.png');
            const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
            const sprite = new THREE.Sprite(spriteMaterial);
            sprite.scale.set(20, 15, 0);
            return sprite;
        }

        if (node.malicious) {
            geometry = new THREE.TorusGeometry(5, 2, 16, 100);
            main_color = "#000000";
        } else {
            switch (node.role) {
                case 'aggregator':
                    geometry = new THREE.SphereGeometry(5);
                    main_color = "#d95f02";
                    break;
                case 'trainer':
                    geometry = new THREE.ConeGeometry(5, 12);
                    main_color = "#7570b3";
                    break;
                case 'server':
                    geometry = new THREE.BoxGeometry(10, 10, 10);
                    main_color = "#1b9e77";
                    break;
                default:
                    break;
            }
        }

        const isSelected = selectedNodes.has(node);
        const color = isSelected ? '#ff0000' : main_color;

        const mesh = new THREE.Mesh(
            geometry,
            new THREE.MeshLambertMaterial({
                color: color,
                transparent: false,
                opacity: 0.75
            })
        );

        if (node.proxy) {
            // Add proxy indicator
            const sprite = createProxySprite();
            mesh.add(sprite);
        }

        return mesh;
    }

    function createProxySprite() {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.font = '80px Arial';
        context.fillText('PROXY', 0, 70);

        const texture = new THREE.CanvasTexture(canvas);
        const spriteMaterial = new THREE.SpriteMaterial({ map: texture });
        const sprite = new THREE.Sprite(spriteMaterial);
        sprite.scale.set(10, 10 * 0.7, 5);
        sprite.position.set(0, 5, 0);

        return sprite;
    }

    function updateGraph() {
        gDataUpdate();
        if (Graph) {
            Graph.graphData(gData);
            // Update link visualization
            Graph.linkColor(link => link.color || '#999')
                .linkWidth(2)
                .linkOpacity(0.6)
                .linkDirectionalParticles(2)
                .linkDirectionalParticleWidth(3)
                .linkDirectionalParticleSpeed(0.01)
                .linkCurvature(0.25)
                .linkDirectionalParticleResolution(2)
                .linkDirectionalParticleColor(() => '#ff0000');
        }
    }

    function gDataUpdate() {
        // Remove duplicated links
        removeDuplicateLinks();
        // Update neighbors
        updateNeighbors();
        // Update IPs and ports
        updateIPsAndPorts();
    }

    function removeDuplicateLinks() {
        for (let i = 0; i < gData.links.length; i++) {
            for (let j = i + 1; j < gData.links.length; j++) {
                if ((gData.links[i].source === gData.links[j].source && gData.links[i].target === gData.links[j].target) ||
                    (gData.links[i].source === gData.links[j].target && gData.links[i].target === gData.links[j].source)) {
                    gData.links.splice(j, 1);
                }
            }
        }
    }

    function updateNeighbors() {
        gData.links.forEach(link => {
            for (let node of gData.nodes) {
                if (node.id === link.source) {
                    node.neighbors.push(link.target);
                }
                if (node.id === link.target) {
                    node.neighbors.push(link.source);
                }
            }
        });

        // Clean up neighbors
        for (let node of gData.nodes) {
            node.neighbors = [...new Set(node.neighbors)].filter(id => id !== node.id);
        }
    }

    function updateIPsAndPorts() {
        const isProcess = document.getElementById("process-radio").checked;
        const baseIP = "192.168.50";

        gData.nodes.forEach((node, index) => {
            node.ip = isProcess ? "127.0.0.1" : `${baseIP}.${index + 2}`;
            node.port = (45001 + index).toString();
        });
    }

    function getMatrix() {
        const matrix = Array(gData.nodes.length).fill().map(() => Array(gData.nodes.length).fill(0));

        gData.links.forEach(link => {
            const source = typeof link.source === 'object' ? link.source.id : link.source;
            const target = typeof link.target === 'object' ? link.target.id : link.target;
            matrix[source][target] = 1;
            matrix[target][source] = 1;
        });

        // Ensure diagonal is 0
        for (let i = 0; i < matrix.length; i++) {
            matrix[i][i] = 0;
        }

        return matrix;
    }

    function handleBackgroundClick() {
        // Clear selected nodes
        selectedNodes.clear();
        // Hide node dropdown if visible
        const dropdown = document.getElementById("node-dropdown");
        if (dropdown) {
            dropdown.style.display = "none";
        }
        // Update graph to reflect changes
        updateGraph();
    }

    function assignRolesByFederationArchitecture() {
        const federationType = document.getElementById("federationArchitecture").value;
        const nodes = gData.nodes;

        if (nodes.length === 0) return;

        switch (federationType) {
            case "CFL":
                // First node as server, rest as trainers
                nodes[0].role = "server";
                for (let i = 1; i < nodes.length; i++) {
                    nodes[i].role = "trainer";
                }
                break;

            case "SDFL":
                // All as trainers except one random node as aggregator
                const randomIndex = Math.floor(Math.random() * nodes.length);
                for (let i = 0; i < nodes.length; i++) {
                    nodes[i].role = i === randomIndex ? "aggregator" : "trainer";
                }
                break;

            case "DFL":
                // All as aggregators
                for (let i = 0; i < nodes.length; i++) {
                    nodes[i].role = "aggregator";
                }
                break;
        }

        // Force complete graph update
        if (Graph) {
            Graph.nodeThreeObject(node => createNodeObject(node));
            Graph.graphData(gData);
        }
        updateGraph();
    }

    // Add event listener for federation architecture changes
    document.getElementById("federationArchitecture").addEventListener("change", function() {
        assignRolesByFederationArchitecture();
    });

    return {
        initializeGraph,
        updateGraphData,
        getGraph: () => Graph,
        getData: () => gData,
        setData: (data) => {
            // Ensure data has the required structure
            if (!data || !data.nodes || !data.links) {
                // If data is invalid, generate a new predefined topology
                generatePredefinedTopology();
                return;
            }

            // Ensure each node has the required properties
            data.nodes = data.nodes.map(node => ({
                id: node.id,
                role: node.role || 'trainer',
                malicious: node.malicious || false,
                proxy: node.proxy || false,
                neighbors: node.neighbors || [],
                links: node.links || []
            }));

            // Ensure each link has the required properties
            data.links = data.links.map(link => ({
                source: link.source,
                target: link.target
            }));

            gData = data;
            updateGraph();
        },
        getMatrix,
        generatePredefinedTopology,
        updateGraph
    };
})();

export default TopologyManager;
