// Monitor page functionality
class Monitor {
    constructor() {
        // Debug flag to control logging
        this.debug = true;

        // Get scenario name from URL path
        const pathParts = window.location.pathname.split('/');
        this.scenarioName = pathParts[pathParts.indexOf('dashboard') + 1];

        this.clearAllData();

        this.isLoadingInitialData = false;
        this.initialDataPromise = null;

        this.initializeMap();
        this.initializeGraph();
        this.initializeWebSocket();
        this.initializeEventListeners();
        this.initializeDownloadHandlers();

        this.startStaleNodeCheck();

        // Load initial data and then start periodic status check
        this.loadInitialData().then(() => {
            this.startPeriodicStatusCheck();
        }).catch(error => {
            this.error('Error during initialization:', error);
            showAlert('danger', 'Error initializing monitor. Please refresh the page.');
        });
    }

    // Helper method to clear all data structures
    clearAllData() {
        this.log('Clearing all data structures');
        this.offlineNodes = new Set();
        this.droneMarkers = {};
        this.droneLines = {};
        this.updateQueue = [];
        this.gData = {
            nodes: [],
            links: []
        };
        this.nodeTimestamps = new Map();
        this.nodePositions = new Map();
        this.isInitialDataLoaded = false;
        this.processingUpdates = false;
        this.pendingGraphUpdate = false;
        if (this.updateTimeout) {
            clearTimeout(this.updateTimeout);
        }

        // Clear the table body
        const tableBody = document.querySelector('#table-nodes tbody');
        if (tableBody) {
            tableBody.innerHTML = '';
        }

        // Clear the map markers and lines
        if (this.lineLayer) {
            this.lineLayer.clearLayers();
        }

        this.log('All data structures cleared');
    }

    // Helper method for logging
    log(...args) {
        if (this.debug) {
            console.log(...args);
        }
    }

    // Helper method for warning logs
    warn(...args) {
        if (this.debug) {
            console.warn(...args);
        }
    }

    // Helper method for error logs
    error(...args) {
        // Always log errors regardless of debug flag
        console.error(...args);
    }

    // Helper method for info logs
    info(...args) {
        if (this.debug) {
            console.info(...args);
        }
    }

    initializeMap() {
        this.log('Initializing map...');
        this.map = L.map('map', {
            center: [38.023522, -1.174389],
            zoom: 17,
            minZoom: 2,
            maxZoom: 18,
            maxBounds: [[-90, -180], [90, 180]],
            maxBoundsViscosity: 1.0,
            zoomControl: true,
            worldCopyJump: false,
        });

        this.log('Adding tile layer...');
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: '&copy; <a href="https://enriquetomasmb.com">enriquetomasmb.com</a>'
        }).addTo(this.map);

        // Initialize line layer
        this.log('Initializing line layer...');
        this.lineLayer = L.layerGroup().addTo(this.map);
        this.log('Line layer added to map:', this.lineLayer);

        // Initialize drone icons
        this.log('Initializing drone icons...');
        this.droneIcon = L.icon({
            iconUrl: '/platform/static/images/drone.svg',
            iconSize: [28, 28],
            iconAnchor: [19, 19],
            popupAnchor: [0, -19]
        });

        this.droneIconOffline = L.icon({
            iconUrl: '/platform/static/images/drone_offline.svg',
            iconSize: [28, 28],
            iconAnchor: [19, 19],
            popupAnchor: [0, -19]
        });

        // Add CSS to style the offline drone icon
        const style = document.createElement('style');
        style.textContent = `
            .leaflet-marker-icon.drone-offline {
                filter: brightness(0) saturate(100%) invert(15%) sepia(100%) saturate(5000%) hue-rotate(350deg) brightness(90%) contrast(100%);
            }
        `;
        document.head.appendChild(style);

        this.log('Map initialization complete');
    }

    initializeGraph() {
        const width = document.getElementById('3d-graph').offsetWidth;

        // Initialize with basic configuration first
        this.Graph = ForceGraph3D()(document.getElementById('3d-graph'))
            .width(width)
            .height(600)
            .backgroundColor('#ffffff')
            .nodeId('ipport')
            .nodeLabel(node => this.createNodeLabel(node))
            .nodeThreeObject(node => this.createNodeObject(node))
            .linkSource('source')
            .linkTarget('target')
            .linkColor(link => {
                const sourceNode = this.gData.nodes.find(n => n.ipport === link.source);
                const targetNode = this.gData.nodes.find(n => n.ipport === link.target);
                return (sourceNode && this.offlineNodes.has(sourceNode.ip)) ||
                       (targetNode && this.offlineNodes.has(targetNode.ip)) ? '#ff0000' : '#999';
            })
            .linkOpacity(0.6)
            .linkWidth(2)
            .linkDirectionalParticles(2)
            .linkDirectionalParticleSpeed(0.005)
            .linkDirectionalParticleWidth(2);

        // Configure forces after basic initialization
        this.Graph
            .d3AlphaDecay(0.02)
            .d3VelocityDecay(0.1)
            .warmupTicks(50)
            .cooldownTicks(50);

        // Set initial camera position
        this.Graph.cameraPosition({ x: 0, y: 0, z: 300 }, { x: 0, y: 0, z: 0 }, 0);

        // Disable navigation info
        const navInfo = document.getElementsByClassName("scene-nav-info")[0];
        if (navInfo) {
            navInfo.style.display = 'none';
        }

        // Handle window resize
        window.addEventListener("resize", () => {
            this.Graph.width(document.getElementById('3d-graph').offsetWidth);
        });
    }

    layoutNodes(nodes) {
        const radius = 50;
        const center = { x: 0, y: 0, z: 0 };

        this.log('Layouting nodes:', nodes);

        return nodes.map((node, i) => {
            // Calculate angle based on node index
            const angle = (2 * Math.PI * i) / nodes.length;

            // Position nodes in a circle on the x-y plane
            const x = center.x + radius * Math.cos(angle);
            const y = center.y + radius * Math.sin(angle);
            const z = center.z;  // Keep all nodes at the same z-level initially

            return {
                ...node,
                x,
                y,
                z,
                fx: x,
                fy: y,
                fz: z
            };
        });
    }

    loadInitialData() {
        if (!this.scenarioName) {
            this.error('No scenario name found in URL');
            return Promise.reject(new Error('No scenario name found'));
        }

        this.isLoadingInitialData = true;
        this.log('Starting initial data load');

        // Clear existing data
        this.clearAllData();

        // Create and store the promise
        this.initialDataPromise = new Promise((resolve, reject) => {
            this.log('Loading initial data for scenario:', this.scenarioName);
            fetch(`/platform/api/dashboard/${this.scenarioName}/monitor`)
                .then(response => {
                    if (!response.ok) {
                        throw new Error(`HTTP error! status: ${response.status}`);
                    }
                    return response.json();
                })
                .then(data => {
                    this.log('Received initial data:', data);
                    if (data.nodes && data.nodes.length > 0) {
                        // Create a Set to track unique nodes
                        const uniqueNodes = new Set();
                        const processedNodes = new Set();

                        data.nodes.forEach(node => {
                            const nodeId = `${node.ip}:${node.port}`;

                            // Skip if we've already processed this node
                            if (processedNodes.has(nodeId)) {
                                this.log('Skipping duplicate node in initial data:', nodeId);
                                return;
                            }
                            processedNodes.add(nodeId);

                            const nodeData = {
                                uid: node.uid,
                                idx: node.idx,
                                ip: node.ip,
                                port: node.port,
                                role: node.role,
                                neighbors: node.neighbors,
                                latitude: node.latitude,
                                longitude: node.longitude,
                                timestamp: node.timestamp,
                                federation: node.federation,
                                round: node.round,
                                scenario_name: node.scenario_name,
                                hash: node.hash,
                                malicious: node.malicious,
                                status: node.status
                            };

                            if (!nodeData.status) {
                                this.offlineNodes.add(nodeData.ip);
                                this.log(`Node ${nodeData.ip}:${nodeData.port} marked as offline from initial data`);
                            }

                            this.updateTableRow(nodeData);

                            this.updateQueue.push(nodeData);

                            this.gData.nodes.push({
                                id: nodeData.idx,
                                ip: nodeData.ip,
                                port: nodeData.port,
                                ipport: nodeId,
                                role: nodeData.role,
                                malicious: nodeData.malicious,
                                color: !nodeData.status ? '#ff0000' : this.getNodeColor({ ipport: nodeId, role: nodeData.role, malicious: nodeData.malicious })
                            });
                        });

                        // Process queue and update visualizations
                        this.processQueue();
                        this.updateGraph();
                    } else {
                        this.log('No nodes in initial data');
                    }
                    this.isInitialDataLoaded = true;
                    this.isLoadingInitialData = false;
                    this.log('Initial data load completed');
                    resolve();
                })
                .catch(error => {
                    this.error('Error loading initial data:', error);
                    this.isLoadingInitialData = false;
                    reject(error);
                });
        });

        return this.initialDataPromise;
    }

    processInitialData(data) {
        this.log('Processing initial data:', data);
        if (!data.nodes_table) {
            this.warn('No nodes table in initial data');
            return;
        }

        // Clear existing data
        this.gData.nodes = [];
        this.gData.links = [];
        this.droneMarkers = {};
        this.droneLines = {};
        this.offlineNodes.clear(); // Clear offline nodes set
        this.nodeTimestamps.clear(); // Clear node timestamps

        // Create a map to track unique nodes by IP:port
        const uniqueNodes = new Map();

        // First pass: create all nodes and track offline nodes
        data.nodes_table.forEach(node => {
            try {
                this.log('Processing node:', node);
                const nodeData = {
                    uid: node.uid,
                    idx: node.idx,
                    ip: node.ip,
                    port: node.port,
                    role: node.role,
                    neighbors: node.neighbors || "",
                    latitude: parseFloat(node.latitude) || 0,
                    longitude: parseFloat(node.longitude) || 0,
                    timestamp: node.timestamp,
                    federation: node.federation,
                    round: node.round,
                    malicious: node.malicious,
                    status: node.status
                };

                this.log('Processed node data:', nodeData);

                // Validate coordinates
                if (isNaN(nodeData.latitude) || isNaN(nodeData.longitude)) {
                    this.warn('Invalid coordinates in initial data for node:', nodeData.uid);
                    // Use default coordinates if invalid
                    nodeData.latitude = 38.023522;
                    nodeData.longitude = -1.174389;
                }

                // Track offline nodes
                if (!nodeData.status) {
                    this.offlineNodes.add(nodeData.ip);
                    this.log('Node marked as offline during initialization:', nodeData.ip);
                }

                // Set initial timestamp
                const initialNodeId = `${nodeData.ip}:${nodeData.port}`;
                this.nodeTimestamps.set(initialNodeId, Date.now());

                // Update table
                this.updateNode(nodeData);

                // Update map
                this.updateQueue.push(nodeData);
                this.log('Added node to update queue:', nodeData.uid);

                // Add node to graph data - ensure uniqueness
                const uniqueNodeId = `${nodeData.ip}:${nodeData.port}`;
                if (!uniqueNodes.has(uniqueNodeId)) {
                    uniqueNodes.set(uniqueNodeId, {
                        id: nodeData.idx,
                        ip: nodeData.ip,
                        port: nodeData.port,
                        ipport: uniqueNodeId,
                        role: nodeData.role,
                        malicious: nodeData.malicious,
                        color: this.getNodeColor({ ipport: uniqueNodeId, role: nodeData.role, malicious: nodeData.malicious })
                    });
                    this.log('Added unique node:', uniqueNodeId);
                } else {
                    this.log('Skipping duplicate node:', uniqueNodeId);
                }
            } catch (error) {
                this.error('Error processing node data:', error);
            }
        });

        // Convert unique nodes map to array
        this.gData.nodes = Array.from(uniqueNodes.values());
        this.log('Total unique nodes:', this.gData.nodes.length);

        // Second pass: create links only between online nodes
        this.log('Creating graph with', this.gData.nodes.length, 'nodes');
        for (let i = 0; i < this.gData.nodes.length; i++) {
            const sourceNode = this.gData.nodes[i];
            const sourceIP = sourceNode.ip;

            // Skip if source node is offline
            if (this.offlineNodes.has(sourceIP)) {
                this.log('Skipping links for offline source node:', sourceIP);
                continue;
            }

            for (let j = i + 1; j < this.gData.nodes.length; j++) {
                const targetNode = this.gData.nodes[j];
                const targetIP = targetNode.ip;

                // Skip if target node is offline
                if (this.offlineNodes.has(targetIP)) {
                    this.log('Skipping link to offline target node:', targetIP);
                    continue;
                }

                // Add bidirectional links only between online nodes
                this.gData.links.push({
                    source: sourceNode.ipport,
                    target: targetNode.ipport,
                    value: this.randomFloatFromInterval(1.0, 1.3)
                });

                this.gData.links.push({
                    source: targetNode.ipport,
                    target: sourceNode.ipport,
                    value: this.randomFloatFromInterval(1.0, 1.3)
                });
            }
        }

        // Process queue immediately
        this.processQueue();

        // Initial graph update
        this.updateGraph();
        this.log('Initial data processing complete. Total links:', this.gData.links.length);
    }

    updateGraphData(data) {
        const nodeId = `${data.ip}:${data.port}`;
        this.log('Updating graph data for node:', nodeId);

        // Add or update node - ensure no duplication
        const existingNodeIndex = this.gData.nodes.findIndex(n => n.ipport === nodeId);
        if (existingNodeIndex === -1) {
            // Only add if node doesn't exist
            const newNode = {
                id: data.idx,
                ip: data.ip,
                port: data.port,
                ipport: nodeId,
                role: data.role,
                malicious: data.malicious,
                color: this.getNodeColor({ ipport: nodeId, role: data.role, malicious: data.malicious })
            };
            this.log('Adding new node to graph:', newNode);
            this.gData.nodes.push(newNode);
        } else {
            // Update existing node
            const updatedNode = {
                ...this.gData.nodes[existingNodeIndex],
                role: data.role,
                malicious: data.malicious,
                color: this.getNodeColor({ ipport: nodeId, role: data.role, malicious: data.malicious })
            };
            this.log('Updating existing node in graph:', updatedNode);
            this.gData.nodes[existingNodeIndex] = updatedNode;
        }

        // If node is offline, remove its links but preserve others
        if (!data.status || this.offlineNodes.has(data.ip)) {
            this.log('Node is offline, removing its links');
            this.gData.links = this.gData.links.filter(link => {
                const sourceIP = typeof link.source === 'object' ? link.source.ipport : link.source;
                const targetIP = typeof link.target === 'object' ? link.target.ipport : link.target;
                return sourceIP !== nodeId && targetIP !== nodeId;
            });
            return;
        }

        // For online nodes, update their connections
        if (data.neighbors) {
            // Parse neighbors using consistent format
            const neighbors = data.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '');
            this.log('Processing neighbors:', neighbors);

            // Get current links for this node
            const currentLinks = this.gData.links.filter(link => {
                const sourceIP = typeof link.source === 'object' ? link.source.ipport : link.source;
                const targetIP = typeof link.target === 'object' ? link.target.ipport : link.target;
                return sourceIP === nodeId || targetIP === nodeId;
            });

            // Create a set of current neighbor IDs
            const currentNeighbors = new Set(
                currentLinks.map(link => {
                    const neighborId = link.source === nodeId ? link.target : link.source;
                    return neighborId;
                })
            );

            // Create a set of new neighbor IDs
            const newNeighbors = new Set(
                neighbors.map(neighbor => {
                    const [neighborIP, neighborPort] = neighbor.split(':');
                    return `${neighborIP}:${neighborPort || data.port}`;
                })
            );

            // Only update if there are actual changes in neighbors
            if (!this.areSetsEqual(currentNeighbors, newNeighbors)) {
                this.log('Neighbor changes detected, updating links');

                // Remove existing links for this node
                this.gData.links = this.gData.links.filter(link => {
                    const sourceIP = typeof link.source === 'object' ? link.source.ipport : link.source;
                    const targetIP = typeof link.target === 'object' ? link.target.ipport : link.target;
                    return sourceIP !== nodeId && targetIP !== nodeId;
                });

                // Add new links for online neighbors
                neighbors.forEach(neighbor => {
                    const neighborIP = neighbor.split(':')[0];
                    if (!this.offlineNodes.has(neighborIP)) {
                        const normalizedNeighbor = neighbor.includes(':') ? neighbor : `${neighbor}:${data.port}`;
                        const neighborNode = this.gData.nodes.find(n =>
                            n.ipport === normalizedNeighbor ||
                            n.ipport.split(':')[0] === neighborIP
                        );

                        if (neighborNode) {
                            this.gData.links.push({
                                source: nodeId,
                                target: normalizedNeighbor,
                                value: 1.0
                            });
                        }
                    }
                });
            } else {
                this.log('No neighbor changes detected, skipping link update');
            }
        }
    }

    randomFloatFromInterval(min, max) {
        return Math.random() * (max - min + 1) + min;
    }

    createNodeLabel(node) {
        return `<p style="color: black">
            <strong>ID:</strong> ${node.id}<br>
            <strong>IP:</strong> ${node.ipport}<br>
            <strong>Role:</strong> ${node.role}
        </p>`;
    }

    createNodeObject(node) {
        const group = new THREE.Group();
        const nodeColor = this.getNodeColor(node);
        const sphereRadius = 5;

        const material = new THREE.MeshBasicMaterial({
            color: nodeColor,
            transparent: true,
            opacity: 0.8,
        });

        const sphere = new THREE.Mesh(
            new THREE.SphereGeometry(sphereRadius, 32, 32),
            material
        );
        group.add(sphere);

        const sprite = new THREE.Sprite(
            new THREE.SpriteMaterial({
                map: this.createTextTexture(`NODE ${node.id}`),
                depthWrite: false,
                depthTest: false
            })
        );

        sprite.scale.set(10, 10 * 0.7, 5);
        sprite.position.set(0, sphereRadius + 2, 0);
        group.add(sprite);

        return group;
    }

    getNodeColor(node) {
        // Check if the node is offline using the IP
        if (this.offlineNodes.has(node.ip)) {
            return '#ff0000'; // Red color for offline nodes
        }

        // Check if the node is malicious
        if (node.malicious === "True" || node.malicious === "true") {
            return '#000000'; // Black color for malicious nodes
        }

        switch(node.role) {
            case 'trainer': return '#7570b3';
            case 'aggregator': return '#d95f02';
            case 'server': return '#1b9e77';
            default: return '#68B0AB';
        }
    }

    createTextTexture(text) {
        const canvas = document.createElement('canvas');
        const context = canvas.getContext('2d');
        context.font = '40px Arial';
        context.fillStyle = 'black';
        context.fillText(text, 0, 40);

        const texture = new THREE.Texture(canvas);
        texture.needsUpdate = true;
        return texture;
    }

    initializeWebSocket() {
        if (!this.scenarioName) return;

        socket.addEventListener("message", (event) => {
            try {
                const data = JSON.parse(event.data);
                if (data.scenario_name !== this.scenarioName) return;

                switch(data.type) {
                    case 'node_update':
                        this.handleNodeUpdate(data);
                        break;
                    case 'node_remove':
                        this.handleNodeRemove(data);
                        break;
                    case 'control':
                        this.log('Control message received:', data);
                        break;
                    default:
                        this.log('Unknown message type:', data.type);
                }
            } catch (e) {
                this.error('Error parsing WebSocket message:', e);
            }
        });
    }

    handleNodeUpdate(data) {
        try {
            // Skip updates if initial data is not loaded yet or if we're still loading initial data
            if (!this.isInitialDataLoaded || this.isLoadingInitialData) {
                this.log('Skipping node update - initial data not loaded yet or still loading');
                return;
            }

            // Validate required fields
            if (!data.uid || !data.ip) {
                this.warn('Missing required fields for node update:', data);
                return;
            }

            const nodeId = `${data.ip}:${data.port}`;

            // Check if this node already exists
            const existingNode = this.gData.nodes.find(n => n.ipport === nodeId);
            if (existingNode) {
                this.log('Updating existing node:', nodeId);
            } else {
                this.log('Adding new node:', nodeId);
            }

            this.log('Handling node update:', data);

            // Update timestamp for this node
            this.nodeTimestamps.set(nodeId, Date.now());

            // First update the table to show changes immediately
            this.updateNode(data);

            // Update graph data with new topology information
            this.updateGraphData(data);

            // Queue the graph update
            this.updateGraph();

            // Process map updates immediately with neighbor distances
            this.processUpdate({
                ...data,
                neighbors_distance: data.neighbors_distance || {}
            });

            // Check if all nodes are offline
            this.checkAllNodesOffline();

            this.log('Node update completed successfully');
        } catch (error) {
            this.error('Error handling node update:', error);
        }
    }

    hasGraphChanges(data) {
        // If no data is provided, return false
        if (!data) return false;

        const nodeId = `${data.ip}:${data.port}`;
        const currentLinks = this.gData.links.filter(link =>
            link.source === nodeId || link.target === nodeId
        );

        if (!data.neighbors) return false;

        // Parse neighbors using consistent format
        const neighbors = data.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '');

        // Create sets of current and new neighbors for comparison
        const currentNeighbors = new Set(
            currentLinks.map(link => {
                const neighborId = link.source === nodeId ? link.target : link.source;
                return neighborId.split(':')[0]; // Compare only IPs
            })
        );

        const newNeighbors = new Set(
            neighbors.map(neighbor => neighbor.split(':')[0]) // Compare only IPs
        );

        // Check if there are any differences in the sets
        if (currentNeighbors.size !== newNeighbors.size) return true;

        for (const neighbor of newNeighbors) {
            if (!currentNeighbors.has(neighbor)) return true;
        }

        return false;
    }

    handleNodeRemove(data) {
        try {
            // Validate required fields
            if (!data.uid || !data.ip) {
                this.warn('Missing required fields for node removal:', data);
                return;
            }

            this.updateNode(data);
            this.removeNodeLinks(data);
            // Update graph data after removing links
            this.updateGraphData(data);
            this.updateGraph();
        } catch (error) {
            this.error('Error handling node removal:', error);
        }
    }

    updateNode(data) {
        if (!data || !data.uid) {
            this.warn('Invalid or missing data for node update:', data);
            return;
        }

        let nodeRow = document.querySelector(`#node-${data.uid}`);

        // If row doesn't exist, create it
        if (!nodeRow) {
            this.log('Creating new row for node:', data.uid);
            const tableBody = document.querySelector('#table-nodes tbody');
            if (!tableBody) {
                this.error('Table body not found');
                return;
            }

            // Create new row
            nodeRow = document.createElement('tr');
            nodeRow.id = `node-${data.uid}`;

            // Create cells matching the HTML template structure
            const cells = [
                { class: 'py-3', content: '' }, // IDX
                { class: 'py-3', content: '' }, // IP
                { class: 'py-3', content: '' }, // Role
                { class: 'py-3', content: '' }, // Round
                { class: 'py-3', content: '' }, // Behaviour
                { class: 'py-3', content: '' }, // Status
                { class: 'py-3', content: '' }  // Actions
            ];

            // Add cells to row
            cells.forEach(cell => {
                const td = document.createElement('td');
                td.className = cell.class;
                td.innerHTML = cell.content;
                nodeRow.appendChild(td);
            });

            // Add row to table
            tableBody.appendChild(nodeRow);
            this.log('New row created for node:', data.uid);
        }

        const nodeId = `${data.ip}:${data.port}`;  // Use full IP:port as nodeId
        const wasOffline = this.offlineNodes.has(nodeId);
        const isNowOffline = !data.status;

        // Update offlineNodes set based on status
        if (isNowOffline) {
            this.offlineNodes.add(nodeId);
            this.log('Node marked as offline:', nodeId);

            // Remove all links for this node
            this.removeNodeLinks(data);

            // Force immediate graph update when node goes offline
            this.updateGraphData(data);
            this.updateGraph();

            // Update marker appearance
            if (this.droneMarkers[data.uid]) {
                this.droneMarkers[data.uid].setIcon(this.droneIconOffline);
                this.droneMarkers[data.uid].getElement().classList.add('drone-offline');
            }
        } else {
            this.offlineNodes.delete(nodeId);
            this.log('Node marked as online:', nodeId);

            // Update marker appearance
            if (this.droneMarkers[data.uid]) {
                this.droneMarkers[data.uid].setIcon(this.droneIcon);
                this.droneMarkers[data.uid].getElement().classList.remove('drone-offline');
            }
        }

        // Update all table cells with latest data
        try {
            // Update IDX
            const idxCell = nodeRow.querySelector('td:nth-child(1)');
            if (idxCell) {
                idxCell.textContent = data.idx || '0';
            }

            // Update IP
            const ipCell = nodeRow.querySelector('td:nth-child(2)');
            if (ipCell) {
                ipCell.textContent = data.ip || '';
            }

            // Update Role
            const roleCell = nodeRow.querySelector('td:nth-child(3)');
            if (roleCell) {
                roleCell.innerHTML = `
                    <span class="badge bg-info-subtle text-black">
                        <i class="fa fa-server me-1"></i>${data.role || 'Unknown'}
                    </span>
                `;
            }

            // Update Round
            const roundCell = nodeRow.querySelector('td:nth-child(4)');
            if (roundCell) {
                roundCell.textContent = data.round || '0';
            }

            // Update Behaviour
            const behaviorCell = nodeRow.querySelector('td:nth-child(5)');
            if (behaviorCell) {
                behaviorCell.innerHTML = data.malicious === "True"
                    ? '<span class="badge bg-dark"><i class="fa fa-skull me-1"></i>Malicious</span>'
                    : '<span class="badge bg-secondary"><i class="fa fa-shield-alt me-1"></i>Benign</span>';
            }

            // Update Status
            const statusCell = nodeRow.querySelector('td:nth-child(6)');
            if (statusCell) {
                statusCell.innerHTML = data.status
                    ? '<span class="badge bg-success"><i class="fa fa-circle me-1"></i>Online</span>'
                    : '<span class="badge bg-danger-subtle text-danger"><i class="fa fa-circle me-1"></i>Offline</span>';
            }

            // Update Actions
            const actionsCell = nodeRow.querySelector('td:nth-child(7)');
            if (actionsCell) {
                const metricsLink = data.hash ? `
                    <li>
                        <a class="dropdown-item" href="/platform/dashboard/${this.scenarioName}/node/${data.hash}/metrics">
                            <i class="fa fa-chart-bar me-2"></i>Real-time metrics
                        </a>
                    </li>
                ` : '';

                actionsCell.innerHTML = `
                    <div class="dropdown d-flex justify-content-center">
                        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button"
                            data-bs-toggle="dropdown" aria-expanded="false">
                            <i class="fa fa-ellipsis-v"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            ${metricsLink}
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/infolog">
                                    <i class="fa fa-file-alt me-2"></i>Download INFO logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/debuglog">
                                    <i class="fa fa-bug me-2"></i>Download DEBUG logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/errorlog">
                                    <i class="fa fa-exclamation-triangle me-2"></i>Download ERROR logs
                                </a>
                            </li>
                        </ul>
                    </div>
                `;
            }

            this.log('Table updated for node:', data.uid);
        } catch (error) {
            this.error('Error updating table cells:', error);
        }

        // Update map position
        this.updateQueue.push(data);
    }

    removeNodeLinks(data) {
        if (!data || !data.ip) {
            this.warn('Invalid data provided to removeNodeLinks:', data);
            return;
        }

        const nodeId = `${data.ip}:${data.port}`;
        this.log('Removing links for node:', nodeId);

        // Remove links from graph data
        const previousLinkCount = this.gData.links.length;

        // Remove all links where this node is either source or target
        this.gData.links = this.gData.links.filter(link => {
            const sourceIP = typeof link.source === 'object' ? link.source.ipport : link.source;
            const targetIP = typeof link.target === 'object' ? link.target.ipport : link.target;
            return sourceIP !== nodeId && targetIP !== nodeId;
        });

        this.log(`Removed ${previousLinkCount - this.gData.links.length} links for node ${nodeId}`);

        // Remove lines from map
        if (data.uid && this.droneLines[data.uid]) {
            this.cleanupDroneLines(data.uid);
        }

        // Update any related lines from other nodes
        if (data.uid) {
            this.updateAllRelatedLines(data.uid);
        }

        // Also remove links from other nodes to this offline node
        Object.entries(this.droneMarkers).forEach(([uid, marker]) => {
            if (marker.neighbors) {
                const neighbors = Array.isArray(marker.neighbors)
                    ? marker.neighbors
                    : (typeof marker.neighbors === 'string'
                        ? marker.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                        : []);

                // If this marker has the offline node as a neighbor, update its lines
                if (neighbors.some(ip => ip.startsWith(data.ip))) {
                    this.updateNeighborLines(uid, marker.getLatLng(), neighbors, true);
                }
            }
        });
    }

    updateGraph(data) {
        if (data) {
            this.updateGraphData(data);
        }

        // Debounce graph updates to prevent multiple rapid updates
        if (this.updateTimeout) {
            clearTimeout(this.updateTimeout);
        }

        this.updateTimeout = setTimeout(() => {
            if (this.pendingGraphUpdate) {
                this.log('Skipping graph update - another update is pending');
                return;
            }

            this.pendingGraphUpdate = true;
            try {
                // Create a new array of nodes with fixed positions
                const layoutedNodes = this.gData.nodes.map((node, index) => {
                    const angle = (2 * Math.PI * index) / this.gData.nodes.length;
                    const radius = 50;

                    return {
                        ...node,
                        x: radius * Math.cos(angle),
                        y: radius * Math.sin(angle),
                        z: 0,
                        fx: radius * Math.cos(angle),
                        fy: radius * Math.sin(angle),
                        fz: 0
                    };
                });

                // Create a new array of links with proper references
                const stableLinks = this.gData.links.map(link => ({
                    source: typeof link.source === 'object' ? link.source.ipport : link.source,
                    target: typeof link.target === 'object' ? link.target.ipport : link.target,
                    value: 1.0
                }));

                this.log('Updating graph with nodes:', layoutedNodes.length, 'and links:', stableLinks.length);

                // Update the graph with new data
                this.Graph.graphData({
                    nodes: layoutedNodes,
                    links: stableLinks
                });
            } finally {
                this.pendingGraphUpdate = false;
            }
        }, 100); // 100ms debounce
    }

    initializeEventListeners() {
        setInterval(() => this.processQueue(), 100);
    }

    initializeDownloadHandlers() {
        const downloadLinks = document.getElementsByClassName('download');
        Array.from(downloadLinks).forEach(link => {
            link.addEventListener('click', (e) => {
                e.preventDefault();
                fetch(link.href)
                    .then(response => {
                        if (!response.ok) {
                            showAlert('danger', 'File not found');
                        } else {
                            window.location.href = link.href;
                        }
                    })
                    .catch(error => {
                        this.error('Error:', error);
                        showAlert('danger', 'Error downloading file');
                    });
            });
        });
    }

    processQueue() {
        if (this.processingUpdates) {
            this.log('Already processing updates, skipping');
            return;
        }

        this.processingUpdates = true;
        try {
            while (this.updateQueue.length > 0) {
                const data = this.updateQueue.shift();
                this.log('Processing queue item:', data);
                this.processUpdate(data);
            }
        } finally {
            this.processingUpdates = false;
        }
    }

    processUpdate(data) {
        try {
            this.log('Processing update for node:', data.uid);

            // Validate required fields
            if (!data.uid || !data.ip) {
                this.warn('Missing required fields for node update:', data);
                return;
            }

            // Convert and validate coordinates
            const lat = parseFloat(data.latitude);
            const lng = parseFloat(data.longitude);

            this.log('Coordinates:', { lat, lng });

            if (isNaN(lat) || isNaN(lng)) {
                this.warn('Invalid coordinates for node:', data.uid, 'lat:', data.latitude, 'lng:', data.longitude);
                // Use default coordinates if invalid
                data.latitude = 38.023522;
                data.longitude = -1.174389;
            }

            // Create validated node data
            const nodeData = {
                ...data,
                latitude: parseFloat(data.latitude),
                longitude: parseFloat(data.longitude),
                neighbors: data.neighbors || "",
                neighbors_distance: data.neighbors_distance || {}
            };

            this.log('Validated node data:', nodeData);

            const newLatLng = new L.LatLng(nodeData.latitude, nodeData.longitude);

            // Parse neighbors string into array, handling both space and comma separators
            const neighborsIPs = nodeData.neighbors
                ? nodeData.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                : [];

            this.log('Parsed neighbor IPs:', neighborsIPs);

            // First update the marker
            this.log('Updating drone position for node:', nodeData.uid);
            this.updateDronePosition(
                nodeData.uid,
                nodeData.ip,
                nodeData.latitude,
                nodeData.longitude,
                neighborsIPs,
                nodeData.neighbors_distance
            );

            // Always update lines, even if there are no neighbors (this will clean up existing lines)
            this.updateNeighborLines(nodeData.uid, newLatLng, neighborsIPs, true);

            // Update any related lines from other nodes
            this.updateAllRelatedLines(nodeData.uid);
        } catch (error) {
            this.error('Error processing update:', error);
        }
    }

    updateDronePosition(uid, ip, lat, lng, neighborIPs, neighborsDistance) {
        this.log('Updating drone position:', { uid, ip, lat, lng });
        const droneId = uid;
        const newLatLng = new L.LatLng(lat, lng);

        // Create popup content with node information
        const popupContent = `
            <div class="drone-popup">
                <h6><i class="fa fa-drone me-2"></i>Node Information</h6>
                <p><strong>IP:</strong> ${ip}</p>
                <p><strong>Location:</strong> ${Number(lat).toFixed(4)}, ${Number(lng).toFixed(4)}</p>
                ${neighborIPs.length > 0 ? `<p><strong>Neighbors:</strong> ${neighborIPs.length}</p>` : ''}
            </div>`;

        if (!this.droneMarkers[droneId]) {
            this.log('Creating new marker for node:', droneId);
            // Create new marker
            const marker = L.marker(newLatLng, {
                icon: this.offlineNodes.has(ip) ? this.droneIconOffline : this.droneIcon,
                title: `Node ${uid}`,
                alt: `Node ${uid}`,
                className: this.offlineNodes.has(ip) ? 'drone-offline' : ''
            }).addTo(this.map);

            marker.bindPopup(popupContent, {
                maxWidth: 300,
                className: 'drone-popup'
            });

            marker.on('mouseover', function() {
                this.openPopup();
            });

            marker.on('mouseout', function() {
                this.closePopup();
            });

            marker.ip = ip;
            marker.neighbors = neighborIPs;
            marker.neighbors_distance = neighborsDistance;
            this.droneMarkers[droneId] = marker;
            this.log('Marker created and added to map:', marker);
        } else {
            this.log('Updating existing marker for node:', droneId);
            // Update existing marker
            if (this.offlineNodes.has(ip)) {
                this.droneMarkers[droneId].setIcon(this.droneIconOffline);
                this.droneMarkers[droneId].getElement().classList.add('drone-offline');
            } else {
                this.droneMarkers[droneId].setIcon(this.droneIcon);
                this.droneMarkers[droneId].getElement().classList.remove('drone-offline');
            }

            this.droneMarkers[droneId].setLatLng(newLatLng);
            this.droneMarkers[droneId].getPopup().setContent(popupContent);
            this.droneMarkers[droneId].neighbors = neighborIPs;
            this.droneMarkers[droneId].neighbors_distance = neighborsDistance;
            this.log('Marker updated:', this.droneMarkers[droneId]);
        }
    }

    updateNeighborLines(droneId, droneLatLng, neighborsIPs, condition) {
        this.log('Updating neighbor lines for drone:', droneId, 'with neighbors:', neighborsIPs);
        this.log('Current drone position:', droneLatLng);

        // Clean up existing lines for this drone
        this.cleanupDroneLines(droneId);

        // If no neighbors or drone is offline, don't create any lines
        if (!neighborsIPs || neighborsIPs.length === 0 || !this.droneMarkers[droneId] || this.offlineNodes.has(this.droneMarkers[droneId].ip)) {
            this.log('No neighbors or drone is offline, skipping line creation');
            return;
        }

        // Initialize droneLines array if it doesn't exist
        if (!this.droneLines[droneId]) {
            this.droneLines[droneId] = [];
        }

        // Create new lines
        neighborsIPs.forEach(neighborIP => {
            // Extract IP from IP:port format if present
            const neighborIPOnly = neighborIP.split(':')[0];
            const neighborMarker = this.findMarkerByIP(neighborIPOnly);

            if (neighborMarker) {
                // Skip if neighbor is offline
                if (this.offlineNodes.has(neighborIPOnly)) {
                    this.log('Skipping line creation - neighbor is offline:', neighborIPOnly);
                    return;
                }

                this.log('Found neighbor marker for IP:', neighborIPOnly);
                const neighborLatLng = neighborMarker.getLatLng();
                this.log('Neighbor position:', neighborLatLng);

                this.log('Creating line between:', droneLatLng, 'and', neighborLatLng);

                try {
                    // Create the line with explicit coordinates
                    const line = L.polyline(
                        [
                            [droneLatLng.lat, droneLatLng.lng],
                            [neighborLatLng.lat, neighborLatLng.lng]
                        ],
                        {
                            color: '#4CAF50',
                            weight: 3,
                            opacity: 1.0,
                            interactive: true
                        }
                    );

                    // Add popup with distance information
                    try {
                        const currentMarker = this.droneMarkers[droneId];
                        const neighborFullIP = neighborIP.includes(':') ? neighborIP : `${neighborIP}:${currentMarker.port}`;

                        // Get distance from the current marker's neighbors_distance object
                        const distance = currentMarker.neighbors_distance &&
                                      currentMarker.neighbors_distance[neighborFullIP];

                        this.log('Distance data:', {
                            marker: currentMarker,
                            neighborFullIP,
                            neighbors_distance: currentMarker.neighbors_distance,
                            distance
                        });

                        line.bindPopup(`
                            <div class="line-popup">
                                <p><strong>Distance:</strong> ${distance ? distance.toFixed(2) + ' m' : 'Calculating...'}</p>
                                <p><strong>Status:</strong> Online</p>
                            </div>
                        `);
                    } catch (err) {
                        this.warn('Error binding popup to line:', err);
                        line.bindPopup('Distance: Calculating...');
                    }

                    // Add hover behavior
                    line.on('mouseover', function() {
                        this.openPopup();
                    });

                    // Add the line to the layer group
                    this.lineLayer.addLayer(line);
                    this.log('Line added to line layer');

                    // Store the line
                    this.droneLines[droneId].push(line);
                    this.log('Line stored in droneLines array');

                } catch (error) {
                    this.error('Error creating/adding line:', error);
                }
            } else {
                this.warn('No marker found for neighbor IP:', neighborIPOnly);
            }
        });
    }

    cleanupDroneLines(droneId) {
        this.log('Cleaning up lines for drone:', droneId);
        if (this.droneLines[droneId]) {
            this.droneLines[droneId].forEach(line => {
                if (line) {
                    try {
                        // Remove from layer group
                        this.lineLayer.removeLayer(line);
                        this.log('Line removed from layer');
                    } catch (error) {
                        this.error('Error removing line:', error);
                    }
                }
            });
        }
        this.droneLines[droneId] = [];
    }

    updateAllRelatedLines(droneId) {
        // Get the current drone's IP
        const currentDroneIP = this.droneMarkers[droneId]?.ip;
        if (!currentDroneIP) {
            this.warn('No IP found for drone:', droneId);
            return;
        }

        this.log('Updating related lines for drone:', droneId, 'with IP:', currentDroneIP);

        // Update lines for all drones that have this drone as a neighbor
        Object.entries(this.droneMarkers).forEach(([id, marker]) => {
            if (id !== droneId && marker.neighbors) {
                this.log('Processing marker:', id, 'with neighbors:', marker.neighbors, 'type:', typeof marker.neighbors);

                // Handle both string and array formats for neighbors
                const neighborIPs = Array.isArray(marker.neighbors)
                    ? marker.neighbors
                    : (typeof marker.neighbors === 'string'
                        ? marker.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                        : []);

                this.log('Processed neighbor IPs:', neighborIPs);

                if (neighborIPs.some(ip => ip.startsWith(currentDroneIP))) {
                    this.log('Found matching neighbor, updating lines');
                    this.updateNeighborLines(
                        id,
                        marker.getLatLng(),
                        neighborIPs,
                        false
                    );
                }
            }
        });
    }

    findMarkerByIP(ip) {
        // Handle both IP and IP:port formats
        const ipOnly = ip.split(':')[0];
        this.log('Looking for marker with IP:', ipOnly);
        this.log('Available markers:', Object.values(this.droneMarkers).map(m => m.ip));

        const marker = Object.values(this.droneMarkers).find(marker => {
            const markerIP = marker.ip.split(':')[0];
            const matches = markerIP === ipOnly;
            if (matches) {
                this.log('Found matching marker:', markerIP);
            }
            return matches;
        });

        if (!marker) {
            this.warn('No marker found for IP:', ipOnly);
        }
        return marker;
    }

    startStaleNodeCheck() {
        // Check for stale nodes every 5 seconds
        setInterval(() => {
            const currentTime = Date.now();
            const staleThreshold = 20000; // 20 seconds in milliseconds

            // Check all nodes for staleness
            this.nodeTimestamps.forEach((timestamp, nodeId) => {
                const timeSinceLastUpdate = currentTime - timestamp;
                if (timeSinceLastUpdate > staleThreshold) {
                    this.log(`Node ${nodeId} is stale (${timeSinceLastUpdate}ms since last update)`);
                    this.markNodeAsOffline(nodeId);
                }
            });
        }, 5000); // Check every 5 seconds
    }

    markNodeAsOffline(nodeId) {
        // Find the node data from our existing data structures
        const node = this.gData.nodes.find(n => n.ipport === nodeId);
        if (!node) {
            this.warn(`Node ${nodeId} not found in graph data`);
            return;
        }

        this.log(`Marking node ${nodeId} as offline`);

        // Add to offline nodes set
        this.offlineNodes.add(node.ip);

        // Update node color in graph data
        const nodeIndex = this.gData.nodes.findIndex(n => n.ipport === nodeId);
        if (nodeIndex !== -1) {
            this.gData.nodes[nodeIndex].color = '#ff0000'; // Red color for offline nodes
        }

        // Remove all links involving this node
        this.gData.links = this.gData.links.filter(link => {
            const sourceIP = typeof link.source === 'object' ? link.source.ipport : link.source;
            const targetIP = typeof link.target === 'object' ? link.target.ipport : link.target;
            return sourceIP !== nodeId && targetIP !== nodeId;
        });

        // Update marker appearance if it exists
        const marker = Object.entries(this.droneMarkers).find(([_, m]) => m.ip === node.ip)?.[1];
        if (marker) {
            marker.setIcon(this.droneIconOffline);
            marker.getElement().classList.add('drone-offline');

            // Remove all lines connected to this node
            if (this.droneLines[marker.uid]) {
                this.cleanupDroneLines(marker.uid);
            }
        }

        // Find the node's UID from the markers
        const nodeEntry = Object.entries(this.droneMarkers).find(([_, m]) => m.ip === node.ip);
        if (!nodeEntry) {
            this.warn(`No marker found for node ${nodeId}`);
            return;
        }

        const [uid, _] = nodeEntry;

        // Update table status
        const nodeRow = document.querySelector(`#node-${uid}`);
        if (nodeRow) {
            const statusCell = nodeRow.querySelector('td:nth-child(6)');
            if (statusCell) {
                statusCell.innerHTML = '<span class="badge bg-danger"><i class="fa fa-circle me-1"></i>Offline</span>';
            }
        }

        // Update graph visualization
        this.updateGraph();

        // Update map visualization
        this.updateAllRelatedLines(uid);
    }

    startPeriodicStatusCheck() {
        this.log("Starting periodic status check");
        this.checkNodeStatus();

        setInterval(() => this.checkNodeStatus(), 5000);
    }

    async checkNodeStatus() {
        try {
            // Skip status check if we're still loading initial data
            if (this.isLoadingInitialData) {
                this.log('Skipping status check - initial data still loading');
                return;
            }

            // Wait for initial data to be loaded if it hasn't completed yet
            if (this.initialDataPromise && !this.isInitialDataLoaded) {
                this.log('Waiting for initial data to complete before status check');
                await this.initialDataPromise;
            }

            const response = await fetch(`/platform/api/dashboard/${this.scenarioName}/monitor`);
            if (!response.ok) {
                this.error('Failed to fetch node status');
                return;
            }

            const data = await response.json();
            if (!data.nodes || data.nodes.length === 0) {
                this.warn('No nodes in status check response');
                return;
            }

            this.log('Received status check data:', data);

            // Create a Set to track processed nodes in this status check
            const processedNodes = new Set();

            data.nodes.forEach(node => {
                const nodeId = `${node.ip}:${node.port}`;

                // Skip if we've already processed this node in this status check
                if (processedNodes.has(nodeId)) {
                    this.log('Skipping duplicate node in status check:', nodeId);
                    return;
                }
                processedNodes.add(nodeId);

                const nodeData = {
                    uid: node.uid,
                    idx: node.idx,
                    ip: node.ip,
                    port: node.port,
                    role: node.role,
                    neighbors: node.neighbors,
                    latitude: node.latitude,
                    longitude: node.longitude,
                    timestamp: node.timestamp,
                    federation: node.federation,
                    round: node.round,
                    scenario_name: node.scenario_name,
                    hash: node.hash,
                    malicious: node.malicious,
                    status: node.status
                };

                if (!nodeData.status) {
                    this.offlineNodes.add(nodeData.ip);
                    this.log(`Node ${nodeData.ip}:${nodeData.port} marked as offline from status check`);
                }

                // Update table row
                this.log("Updating table row for node:", nodeData);
                this.updateTableRow(nodeData);

                // Update map marker if it exists
                if (this.droneMarkers[nodeData.uid]) {
                    // Preserve existing neighbor distances
                    const existingMarker = this.droneMarkers[nodeData.uid];
                    const neighborsDistance = existingMarker.neighbors_distance || {};

                    this.updateDronePosition(
                        nodeData.uid,
                        nodeData.ip,
                        parseFloat(nodeData.latitude),
                        parseFloat(nodeData.longitude),
                        nodeData.neighbors ? nodeData.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '') : [],
                        neighborsDistance
                    );
                }
            });

            this.updateGraphDataFromStatus(data.nodes);

            // Update all visualizations
            this.updateGraph();
            this.updateAllMarkers();
            this.updateAllRelatedLines();

            // Check if all nodes are offline
            this.checkAllNodesOffline();
        } catch (error) {
            this.error('Error in status check:', error);
        }
    }

    updateTableRow(data) {
        // Validate required data
        if (!data || !data.uid) {
            this.warn('Invalid or missing data for table row update:', data);
            return;
        }

        let nodeRow = document.querySelector(`#node-${data.uid}`);

        // If row doesn't exist, create it
        if (!nodeRow) {
            this.log('Creating new row for node:', data.uid);
            const tableBody = document.querySelector('#table-nodes tbody');
            if (!tableBody) {
                this.error('Table body not found');
                return;
            }

            // Create new row
            nodeRow = document.createElement('tr');
            nodeRow.id = `node-${data.uid}`;

            // Create cells with initial values
            const cells = [
                { class: 'py-3', content: data.idx || '0' }, // IDX
                { class: 'py-3', content: data.ip || '' }, // IP
                { class: 'py-3', content: `
                    <span class="badge bg-info-subtle text-black">
                        <i class="fa fa-server me-1"></i>${data.role || 'Unknown'}
                    </span>
                ` }, // Role
                { class: 'py-3', content: data.round || '0' }, // Round
                { class: 'py-3', content: data.malicious === "True" || data.malicious === "true"
                    ? '<span class="badge bg-dark"><i class="fa fa-skull me-1"></i>Malicious</span>'
                    : '<span class="badge bg-secondary"><i class="fa fa-shield-alt me-1"></i>Benign</span>' }, // Behaviour
                { class: 'py-3', content: data.status
                    ? '<span class="badge bg-success"><i class="fa fa-circle me-1"></i>Online</span>'
                    : '<span class="badge bg-danger-subtle text-danger"><i class="fa fa-circle me-1"></i>Offline</span>' }, // Status
                { class: 'py-3', content: `
                    <div class="dropdown d-flex justify-content-center">
                        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button"
                            data-bs-toggle="dropdown" aria-expanded="false">
                            <i class="fa fa-ellipsis-v"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            ${data.hash ? `
                                <li>
                                    <a class="dropdown-item" href="/platform/dashboard/${this.scenarioName}/node/${data.hash}/metrics">
                                        <i class="fa fa-chart-bar me-2"></i>Real-time metrics
                                    </a>
                                </li>
                            ` : ''}
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/infolog">
                                    <i class="fa fa-file-alt me-2"></i>Download INFO logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/debuglog">
                                    <i class="fa fa-bug me-2"></i>Download DEBUG logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/errorlog">
                                    <i class="fa fa-exclamation-triangle me-2"></i>Download ERROR logs
                                </a>
                            </li>
                        </ul>
                    </div>
                ` }  // Actions
            ];

            // Add cells to row with their initial values
            cells.forEach(cell => {
                const td = document.createElement('td');
                td.className = cell.class;
                td.innerHTML = cell.content;
                nodeRow.appendChild(td);
            });

            // Add row to table
            tableBody.appendChild(nodeRow);
            this.log('New row created with initial values for node:', data.uid);
            return; // Exit since we've already set all values
        }

        // Update existing row cells with latest data
        try {
            // Update IDX
            const idxCell = nodeRow.querySelector('td:nth-child(1)');
            if (idxCell) {
                idxCell.textContent = data.idx || '0';
            }

            // Update IP
            const ipCell = nodeRow.querySelector('td:nth-child(2)');
            if (ipCell) {
                ipCell.textContent = data.ip || '';
            }

            // Update Role
            const roleCell = nodeRow.querySelector('td:nth-child(3)');
            if (roleCell) {
                roleCell.innerHTML = `
                    <span class="badge bg-info-subtle text-black">
                        <i class="fa fa-server me-1"></i>${data.role || 'Unknown'}
                    </span>
                `;
            }

            // Update Round
            const roundCell = nodeRow.querySelector('td:nth-child(4)');
            if (roundCell) {
                roundCell.textContent = data.round || '0';
            }

            // Update Behaviour
            const behaviorCell = nodeRow.querySelector('td:nth-child(5)');
            if (behaviorCell) {
                behaviorCell.innerHTML = data.malicious === "True" || data.malicious === "true"
                    ? '<span class="badge bg-dark"><i class="fa fa-skull me-1"></i>Malicious</span>'
                    : '<span class="badge bg-secondary"><i class="fa fa-shield-alt me-1"></i>Benign</span>';
            }

            // Update Status
            const statusCell = nodeRow.querySelector('td:nth-child(6)');
            if (statusCell) {
                statusCell.innerHTML = data.status
                    ? '<span class="badge bg-success"><i class="fa fa-circle me-1"></i>Online</span>'
                    : '<span class="badge bg-danger-subtle text-danger"><i class="fa fa-circle me-1"></i>Offline</span>';
            }

            // Update Actions
            const actionsCell = nodeRow.querySelector('td:nth-child(7)');
            if (actionsCell) {
                const metricsLink = data.hash ? `
                    <li>
                        <a class="dropdown-item" href="/platform/dashboard/${this.scenarioName}/node/${data.hash}/metrics">
                            <i class="fa fa-chart-bar me-2"></i>Real-time metrics
                        </a>
                    </li>
                ` : '';

                actionsCell.innerHTML = `
                    <div class="dropdown d-flex justify-content-center">
                        <button class="btn btn-sm btn-outline-secondary dropdown-toggle" type="button"
                            data-bs-toggle="dropdown" aria-expanded="false">
                            <i class="fa fa-ellipsis-v"></i>
                        </button>
                        <ul class="dropdown-menu dropdown-menu-end">
                            ${metricsLink}
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/infolog">
                                    <i class="fa fa-file-alt me-2"></i>Download INFO logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/debuglog">
                                    <i class="fa fa-bug me-2"></i>Download DEBUG logs
                                </a>
                            </li>
                            <li>
                                <a class="dropdown-item download" href="/platform/dashboard/${this.scenarioName}/node/${data.idx}/errorlog">
                                    <i class="fa fa-exclamation-triangle me-2"></i>Download ERROR logs
                                </a>
                            </li>
                        </ul>
                    </div>
                `;
            }
        } catch (error) {
            this.error('Error updating table cells:', error);
        }
    }

    updateGraphDataFromStatus(nodesTable) {
        // Clear existing data
        this.gData.nodes = [];
        this.gData.links = [];

        // Create nodes
        nodesTable.forEach(node => {
            const nodeId = `${node.ip}:${node.port}`;
            this.gData.nodes.push({
                id: node.idx,
                ip: node.ip,
                port: node.port,
                ipport: nodeId,
                role: node.role,
                malicious: node.malicious,
                color: !node.status ? '#ff0000' : this.getNodeColor({ ipport: nodeId, role: node.role, malicious: node.malicious })
            });
        });

        // Create links between online nodes
        nodesTable.forEach(sourceNode => {
            if (sourceNode.status && sourceNode.neighbors) {
                const neighbors = sourceNode.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '');
                neighbors.forEach(neighbor => {
                    const [neighborIP, neighborPort] = neighbor.split(':');
                    const targetNode = nodesTable.find(n => n.ip === neighborIP && n.port === neighborPort);
                    if (targetNode && targetNode.status) {
                        this.gData.links.push({
                            source: `${sourceNode.ip}:${sourceNode.port}`,
                            target: `${neighborIP}:${neighborPort}`,
                            value: this.randomFloatFromInterval(1.0, 1.3)
                        });
                    }
                });
            }
        });
    }

    updateAllMarkers() {
        Object.entries(this.droneMarkers).forEach(([uid, marker]) => {
            const ip = marker.ip;
            if (this.offlineNodes.has(ip)) {
                marker.setIcon(this.droneIconOffline);
                marker.getElement().classList.add('drone-offline');
            } else {
                marker.setIcon(this.droneIcon);
                marker.getElement().classList.remove('drone-offline');
            }
        });
    }

    checkAllNodesOffline() {
        // Get all unique node IPs from markers
        const allNodeIPs = new Set(Object.values(this.droneMarkers).map(marker => marker.ip));

        // Check if all nodes are in the offlineNodes set
        const allOffline = allNodeIPs.size > 0 && Array.from(allNodeIPs).every(ip => this.offlineNodes.has(ip));

        // Update scenario status badge
        const statusBadge = document.getElementById('scenario_status');
        if (statusBadge) {
            if (allNodeIPs.size === 0) {
                // Show Running status when there are no nodes
                statusBadge.className = 'badge bg-warning-subtle text-warning px-3 py-2 ms-3';
                statusBadge.innerHTML = '<i class="fa fa-spinner fa-spin me-2"></i>Running';
            } else if (allOffline) {
                statusBadge.className = 'badge bg-danger-subtle text-danger px-3 py-2 ms-3';
                statusBadge.innerHTML = '<i class="fa fa-times-circle me-2"></i>Finished';
                const stopButton = document.getElementById('stop_button');
                if (stopButton) {
                    stopButton.style.display = 'none';
                }
            } else {
                statusBadge.className = 'badge bg-warning-subtle text-warning px-3 py-2 ms-3';
                statusBadge.innerHTML = '<i class="fa fa-spinner fa-spin me-2"></i>Running';
            }
        }
    }

    // Helper method to compare two sets
    areSetsEqual(a, b) {
        if (a.size !== b.size) return false;
        for (const item of a) {
            if (!b.has(item)) return false;
        }
        return true;
    }
}

// Initialize monitor when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new Monitor();
});
