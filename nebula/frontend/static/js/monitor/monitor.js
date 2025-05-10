// Monitor page functionality
class Monitor {
    constructor() {
        // Get scenario name from URL path
        const pathParts = window.location.pathname.split('/');
        this.scenarioName = pathParts[pathParts.indexOf('dashboard') + 1];
        this.offlineNodes = new Set();
        this.droneMarkers = {};
        this.droneLines = {};
        this.updateQueue = [];
        this.gData = {
            nodes: [],
            links: []
        };
        
        this.initializeMap();
        this.initializeGraph();
        this.initializeWebSocket();
        this.initializeEventListeners();
        this.initializeDownloadHandlers();
        this.loadInitialData();
    }

    initializeMap() {
        console.log('Initializing map...');
        this.map = L.map('map', {
            center: [44.194021, 12.397141],
            zoom: 4,
            minZoom: 2,
            maxZoom: 18,
            maxBounds: [[-90, -180], [90, 180]],
            maxBoundsViscosity: 1.0,
            zoomControl: true,
            worldCopyJump: false,
        });

        console.log('Adding tile layer...');
        L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
            attribution: '&copy; <a href="https://enriquetomasmb.com">enriquetomasmb.com</a>'
        }).addTo(this.map);

        this.lineLayer = L.layerGroup().addTo(this.map);
        
        // Initialize drone icons
        console.log('Initializing drone icons...');
        this.droneIcon = L.icon({
            iconUrl: '/platform/static/images/drone.svg',
            iconSize: [38, 38],
            iconAnchor: [19, 19],
            popupAnchor: [0, -19]
        });

        this.droneIconOffline = L.icon({
            iconUrl: '/platform/static/images/drone_offline.svg',
            iconSize: [38, 38],
            iconAnchor: [19, 19],
            popupAnchor: [0, -19]
        });

        console.log('Map initialization complete');
    }

    initializeGraph() {
        const width = document.getElementById('3d-graph').offsetWidth;
        
        this.Graph = ForceGraph3D()(document.getElementById('3d-graph'))
            .width(width)
            .height(600)
            .backgroundColor('#ffffff')
            .nodeId('ipport')
            .nodeLabel(node => this.createNodeLabel(node))
            .onNodeClick(node => this.handleNodeClick(node))
            .nodeThreeObject(node => this.createNodeObject(node))
            .linkSource('source')
            .linkTarget('target')
            .linkColor(link => link.color ? 'red' : '#999')
            .linkOpacity(0.6)
            .linkWidth(2)
            .linkDirectionalParticles(2)
            .linkDirectionalParticleSpeed(0.005)
            .linkDirectionalParticleWidth(2);

        // Configure forces after initialization
        this.Graph.d3Force('charge').strength(-100);
        this.Graph.d3Force('link').distance(100);

        this.Graph.cameraPosition({ x: 0, y: 0, z: 500 }, { x: 0, y: 0, z: 0 }, 0);
        document.getElementsByClassName("scene-nav-info")[0].innerHTML = 
            "Only visualization purpose. Click on a node to zoom in.";

        window.addEventListener("resize", () => {
            this.Graph.width(document.getElementById('3d-graph').offsetWidth);
        });
    }

    loadInitialData() {
        if (!this.scenarioName) {
            console.error('No scenario name found in URL');
            return;
        }

        console.log('Loading initial data for scenario:', this.scenarioName);
        fetch(`/platform/api/dashboard/${this.scenarioName}/monitor`)
            .then(response => {
                if (!response.ok) {
                    throw new Error(`HTTP error! status: ${response.status}`);
                }
                return response.json();
            })
            .then(data => {
                console.log('Received initial data:', data);
                this.processInitialData(data);
            })
            .catch(error => {
                console.error('Error loading initial data:', error);
                showAlert('danger', 'Error loading initial data. Please refresh the page.');
            });
    }

    processInitialData(data) {
        console.log('Processing initial data:', data);
        if (!data.nodes_table) {
            console.warn('No nodes table in initial data');
            return;
        }

        // Clear existing data
        this.gData.nodes = [];
        this.gData.links = [];
        this.droneMarkers = {};
        this.droneLines = {};
        this.lineLayer.clearLayers();

        data.nodes_table.forEach(node => {
            try {
                console.log('Processing node:', node);
                const nodeData = {
                    uid: node[0],
                    idx: node[1],
                    ip: node[2],
                    port: node[3],
                    role: node[4],
                    neighbors: node[5] || "",
                    latitude: parseFloat(node[6]) || 0,
                    longitude: parseFloat(node[7]) || 0,
                    timestamp: node[8],
                    federation: node[9],
                    round: node[10],
                    malicious: node[13],
                    status: node[14]
                };

                console.log('Processed node data:', nodeData);

                // Validate coordinates
                if (isNaN(nodeData.latitude) || isNaN(nodeData.longitude)) {
                    console.warn('Invalid coordinates in initial data for node:', nodeData.uid);
                    // Use default coordinates if invalid
                    nodeData.latitude = 38.023522;
                    nodeData.longitude = -1.174389;
                }

                // Update table
                this.updateNode(nodeData);

                // Update map
                this.updateQueue.push(nodeData);
                console.log('Added node to update queue:', nodeData.uid);

                // Update graph
                this.updateGraphData(nodeData);
            } catch (error) {
                console.error('Error processing node data:', error);
            }
        });

        // Process queue immediately
        this.processQueue();
        
        // Initial graph update
        this.updateGraph();
        console.log('Initial data processing complete');
    }

    updateGraphData(data) {
        const nodeId = `${data.ip}:${data.port}`;
        
        // Add or update node
        const existingNodeIndex = this.gData.nodes.findIndex(n => n.ipport === nodeId);
        if (existingNodeIndex === -1) {
            this.gData.nodes.push({
                id: data.idx,
                ip: data.ip,
                port: data.port,
                ipport: nodeId,
                role: data.role,
                color: this.getNodeColor({ ipport: nodeId, role: data.role })
            });
        } else {
            this.gData.nodes[existingNodeIndex].color = this.getNodeColor({ 
                ipport: nodeId, 
                role: data.role 
            });
        }

        // Update links only if the node is online
        if (!this.offlineNodes.has(nodeId) && data.neighbors) {
            const neighbors = data.neighbors.split(" ");
            const currentLinks = this.gData.links.filter(link => 
                link.source === nodeId || link.target === nodeId
            );
            
            // Remove links to neighbors that are no longer connected
            this.gData.links = this.gData.links.filter(link => {
                if (link.source === nodeId) {
                    return neighbors.includes(link.target);
                }
                if (link.target === nodeId) {
                    return neighbors.includes(link.source);
                }
                return true;
            });

            // Add new links
            neighbors.forEach(neighbor => {
                if (!this.offlineNodes.has(neighbor)) {
                    const linkExists = this.gData.links.some(link => 
                        (link.source === nodeId && link.target === neighbor) ||
                        (link.source === neighbor && link.target === nodeId)
                    );

                    if (!linkExists) {
                        this.gData.links.push({
                            source: nodeId,
                            target: neighbor,
                            value: this.randomFloatFromInterval(1.0, 1.3)
                        });
                    }
                }
            });
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

    handleNodeClick(node) {
        const distance = 40;
        const distRatio = 1 + distance / Math.hypot(node.x, node.y, node.z);
        const newPos = node.x || node.y || node.z
            ? { x: node.x * distRatio, y: node.y * distRatio, z: node.z * distRatio }
            : { x: 0, y: 0, z: distance };
        
        this.Graph.cameraPosition(newPos, node, 3000);
    }

    createNodeObject(node) {
        const group = new THREE.Group();
        const nodeColor = this.getNodeColor(node);
        const sphereRadius = 5;

        const material = new THREE.MeshBasicMaterial({
            color: nodeColor,
            transparent: true,
            opacity: 0.5,
        });
        
        const sphere = new THREE.Mesh(
            new THREE.SphereGeometry(5, 32, 32), 
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
        sprite.position.set(0, 5, 0);
        group.add(sprite);

        return group;
    }

    getNodeColor(node) {
        if (this.offlineNodes.has(node.ipport)) return 'grey';
        
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
                        console.log('Control message received:', data);
                        break;
                    default:
                        console.log('Unknown message type:', data.type);
                }
            } catch (e) {
                console.error('Error parsing WebSocket message:', e);
            }
        });
    }

    handleNodeUpdate(data) {
        try {
            // Validate required fields
            if (!data.uid || !data.ip) {
                console.warn('Missing required fields for node update:', data);
                return;
            }

            this.updateNode(data);
            // Update graph data first, then update the visualization
            this.updateGraphData(data);
            // Only update the graph if there are actual changes
            if (this.hasGraphChanges(data)) {
                this.updateGraph();
            }
        } catch (error) {
            console.error('Error handling node update:', error);
        }
    }

    hasGraphChanges(data) {
        const nodeId = `${data.ip}:${data.port}`;
        const currentLinks = this.gData.links.filter(link => 
            link.source === nodeId || link.target === nodeId
        );
        
        if (!data.neighbors) return false;
        
        const neighbors = data.neighbors.split(" ");
        const currentNeighbors = new Set(
            currentLinks.map(link => 
                link.source === nodeId ? link.target : link.source
            )
        );
        
        return !neighbors.every(neighbor => currentNeighbors.has(neighbor)) ||
               currentNeighbors.size !== neighbors.length;
    }

    handleNodeRemove(data) {
        try {
            // Validate required fields
            if (!data.uid || !data.ip) {
                console.warn('Missing required fields for node removal:', data);
                return;
            }

            this.updateNode(data);
            this.removeNodeLinks(data);
            // Update graph data after removing links
            this.updateGraphData(data);
            this.updateGraph();
        } catch (error) {
            console.error('Error handling node removal:', error);
        }
    }

    updateNode(data) {
        const nodeRow = document.querySelector(`#node-${data.uid}`);
        if (!nodeRow) return;

        // Update status badge
        const statusCell = nodeRow.querySelector('#status');
        if (statusCell) {
            statusCell.innerHTML = data.status 
                ? '<span class="badge bg-success"><i class="fa fa-circle me-1"></i>Online</span>'
                : '<span class="badge bg-danger"><i class="fa fa-circle me-1"></i>Offline</span>';
        }

        // Update behavior badge
        const behaviorCell = nodeRow.querySelector('#malicious');
        if (behaviorCell) {
            behaviorCell.innerHTML = data.malicious === "True"
                ? '<span class="badge bg-dark"><i class="fa fa-skull me-1"></i>Malicious</span>'
                : '<span class="badge bg-secondary"><i class="fa fa-shield-alt me-1"></i>Benign</span>';
        }

        // Update round
        const roundCell = nodeRow.querySelector('#round');
        if (roundCell) {
            roundCell.textContent = data.round;
        }

        // Update map position
        this.updateQueue.push(data);
    }

    removeNodeLinks(data) {
        const nodeId = `${data.ip}:${data.port}`;
        const previousLinkCount = this.gData.links.length;
        
        this.gData.links = this.gData.links.filter(link => 
            link.source !== nodeId && link.target !== nodeId
        );
        
        // Only update if links were actually removed
        if (previousLinkCount !== this.gData.links.length) {
            this.updateGraph();
        }
    }

    updateGraph(data) {
        if (data) {
            // Update graph data with new node information
            this.updateGraphData(data);
        }
        
        // Ensure all links have valid source and target nodes
        this.gData.links = this.gData.links.filter(link => {
            const sourceExists = this.gData.nodes.some(n => n.ipport === link.source);
            const targetExists = this.gData.nodes.some(n => n.ipport === link.target);
            return sourceExists && targetExists;
        });

        // Update the graph with new data
        this.Graph.graphData({
            nodes: this.gData.nodes,
            links: this.gData.links
        });

        // Force a re-render only if there are changes
        if (this.gData.links.length > 0) {
            this.Graph.d3ReheatSimulation();
        }
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
                        console.error('Error:', error);
                        showAlert('danger', 'Error downloading file');
                    });
            });
        });
    }

    processQueue() {
        while (this.updateQueue.length > 0) {
            const data = this.updateQueue.shift();
            console.log('Processing queue item:', data);
            this.processUpdate(data);
        }
    }

    processUpdate(data) {
        try {
            console.log('Processing update for node:', data.uid);
            
            // Validate required fields
            if (!data.uid || !data.ip) {
                console.warn('Missing required fields for node update:', data);
                return;
            }

            // Convert and validate coordinates
            const lat = parseFloat(data.latitude);
            const lng = parseFloat(data.longitude);

            console.log('Coordinates:', { lat, lng });

            if (isNaN(lat) || isNaN(lng)) {
                console.warn('Invalid coordinates for node:', data.uid, 'lat:', data.latitude, 'lng:', data.longitude);
                return;
            }

            // Create validated node data
            const nodeData = {
                ...data,
                latitude: lat,
                longitude: lng,
                neighbors: data.neighbors || ""
            };

            console.log('Validated node data:', nodeData);

            const newLatLng = new L.LatLng(lat, lng);
            const neighborsIPs = nodeData.neighbors ? nodeData.neighbors.split(" ") : [];

            console.log('Updating drone position for node:', nodeData.uid);
            this.updateDronePosition(
                nodeData.uid, 
                nodeData.ip, 
                lat, 
                lng, 
                neighborsIPs, 
                nodeData.neighbors_distance
            );

            if (neighborsIPs.length > 0) {
                console.log('Updating neighbor lines for node:', nodeData.uid);
                setTimeout(() => {
                    this.updateNeighborLines(nodeData.uid, newLatLng, neighborsIPs, true);
                    this.updateAllRelatedLines(nodeData.uid);
                }, 100);
            }
        } catch (error) {
            console.error('Error processing update:', error);
        }
    }

    updateDronePosition(uid, ip, lat, lng, neighborIPs, neighborsDistance) {
        console.log('Updating drone position:', { uid, ip, lat, lng });
        const droneId = uid;
        const newLatLng = new L.LatLng(lat, lng);
        
        // Create popup content with node information
        const popupContent = `
            <div class="drone-popup">
                <h6><i class="fa fa-drone me-2"></i>Node Information</h6>
                <p class="mb-1"><strong>UID:</strong> ${uid}</p>
                <p class="mb-1"><strong>IP:</strong> ${ip}</p>
                <p class="mb-1"><strong>Location:</strong> ${Number(lat).toFixed(4)}, ${Number(lng).toFixed(4)}</p>
                ${neighborIPs.length > 0 ? `<p class="mb-1"><strong>Neighbors:</strong> ${neighborIPs.length}</p>` : ''}
            </div>`;

        if (!this.droneMarkers[droneId]) {
            console.log('Creating new marker for node:', droneId);
            // Create new marker
            const marker = L.marker(newLatLng, {
                icon: this.offlineNodes.has(ip) ? this.droneIconOffline : this.droneIcon,
                title: `Node ${uid}`,
                alt: `Node ${uid}`
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
            console.log('Marker created and added to map:', marker);
        } else {
            console.log('Updating existing marker for node:', droneId);
            // Update existing marker
            if (this.offlineNodes.has(ip)) {
                this.droneMarkers[droneId].setIcon(this.droneIconOffline);
            } else {
                this.droneMarkers[droneId].setIcon(this.droneIcon);
            }

            this.droneMarkers[droneId].setLatLng(newLatLng);
            this.droneMarkers[droneId].getPopup().setContent(popupContent);
            this.droneMarkers[droneId].neighbors = neighborIPs;
            this.droneMarkers[droneId].neighbors_distance = neighborsDistance;
            console.log('Marker updated:', this.droneMarkers[droneId]);
        }
    }

    updateNeighborLines(droneId, droneLatLng, neighborsIPs, condition) {
        if (!this.droneLines[droneId]) {
            this.droneLines[droneId] = [];
        } else {
            this.droneLines[droneId].forEach(line => {
                this.lineLayer.removeLayer(line);
            });
            this.droneLines[droneId] = [];
        }

        neighborsIPs.forEach(neighborIP => {
            const neighborMarker = this.findMarkerByIP(neighborIP);
            if (neighborMarker) {
                const neighborLatLng = neighborMarker.getLatLng();
                const isOffline = this.offlineNodes.has(this.droneMarkers[droneId].ip) || 
                                this.offlineNodes.has(neighborIP);
                
                const line = L.polyline(
                    [droneLatLng, neighborLatLng],
                    { 
                        color: isOffline ? '#ff4444' : '#4CAF50',
                        weight: 2,
                        opacity: 0.8,
                        dashArray: isOffline ? '5, 5' : null
                    }
                ).addTo(this.lineLayer);

                try {
                    const distance = condition 
                        ? this.droneMarkers[droneId].neighbors_distance[neighborIP]
                        : neighborMarker.neighbors_distance[this.droneMarkers[droneId].ip];
                    
                    line.bindPopup(`
                        <div class="line-popup">
                            <p class="mb-1"><strong>Distance:</strong> ${distance ? distance + ' m' : 'Calculating...'}</p>
                            <p class="mb-0"><strong>Status:</strong> ${isOffline ? 'Offline' : 'Online'}</p>
                        </div>
                    `);
                } catch (err) {
                    line.bindPopup('Distance: Calculating...');
                }

                line.on('mouseover', function() {
                    this.openPopup();
                });

                this.droneLines[droneId].push(line);
            }
        });
    }

    updateAllRelatedLines(droneId) {
        Object.keys(this.droneMarkers).forEach(id => {
            if (id !== droneId) {
                const neighborIPs = this.droneMarkers[id].neighbors;
                if (neighborIPs.includes(this.droneMarkers[droneId].ip)) {
                    this.updateNeighborLines(
                        id,
                        this.droneMarkers[id].getLatLng(),
                        neighborIPs,
                        false
                    );
                }
            }
        });
    }

    findMarkerByIP(ip) {
        return Object.values(this.droneMarkers).find(marker => marker.ip === ip);
    }
}

// Initialize monitor when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new Monitor();
}); 