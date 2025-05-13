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
            center: [38.023522, -1.174389],
            zoom: 17,
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

        // Initialize line layer
        console.log('Initializing line layer...');
        this.lineLayer = L.layerGroup().addTo(this.map);
        console.log('Line layer added to map:', this.lineLayer);
        
        // Initialize drone icons
        console.log('Initializing drone icons...');
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
            .linkColor(link => {
                const sourceNode = this.gData.nodes.find(n => n.ipport === link.source);
                const targetNode = this.gData.nodes.find(n => n.ipport === link.target);
                return (sourceNode && this.offlineNodes.has(sourceNode.ipport)) || 
                       (targetNode && this.offlineNodes.has(targetNode.ipport)) ? '#ff0000' : '#999';
            })
            .linkOpacity(0.6)
            .linkWidth(2)
            .linkDirectionalParticles(2)
            .linkDirectionalParticleSpeed(0.005)
            .linkDirectionalParticleWidth(2)
            .d3AlphaDecay(0.01)  // Slower decay for smoother updates
            .d3VelocityDecay(0.3)  // Less damping for more dynamic movement
            .warmupTicks(100)  // Add warmup for better initial layout
            .cooldownTicks(100)  // Add cooldown for smoother transitions
            .d3Force('center', d3.forceCenter().strength(0))  // Even stronger center force
            .d3Force('charge', d3.forceManyBody().strength(0))  // Reduced repulsion
            .d3Force('link', d3.forceLink().id(d => d.ipport).distance(30));  // Reduced link distance

        this.Graph.cameraPosition({ x: 0, y: 0, z: 300 }, { x: 0, y: 0, z: 0 }, 0);

        const navInfo = document.getElementsByClassName("scene-nav-info")[0];
        if (navInfo) {
            navInfo.style.display = 'none';
        }

        window.addEventListener("resize", () => {
            this.Graph.width(document.getElementById('3d-graph').offsetWidth);
        });
    }

    layoutNodes(nodes) {
        const radius = 50; // Radius of the circle
        const center = { x: 0, y: 0, z: 0 };
        
        nodes.forEach((node, i) => {
            const angle = (i / nodes.length) * 2 * Math.PI;
            // Add a small offset to ensure nodes don't overlap at center
            const offset = 5;
            node.x = center.x + (radius + offset) * Math.cos(angle);
            node.y = center.y + (radius + offset) * Math.sin(angle);
            node.z = center.z;
        });
        
        return nodes;
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
        this.offlineNodes.clear(); // Clear offline nodes set

        // Create a map to track unique nodes by IP:port
        const uniqueNodes = new Map();

        // First pass: create all nodes and track offline nodes
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

                // Track offline nodes
                if (!nodeData.status) {
                    this.offlineNodes.add(nodeData.ip);
                    console.log('Node marked as offline during initialization:', nodeData.ip);
                }

                // Update table
                this.updateNode(nodeData);

                // Update map
                this.updateQueue.push(nodeData);
                console.log('Added node to update queue:', nodeData.uid);

                // Add node to graph data - ensure uniqueness
                const nodeId = `${nodeData.ip}:${nodeData.port}`;
                if (!uniqueNodes.has(nodeId)) {
                    uniqueNodes.set(nodeId, {
                        id: nodeData.idx,
                        ip: nodeData.ip,
                        port: nodeData.port,
                        ipport: nodeId,
                        role: nodeData.role,
                        color: this.getNodeColor({ ipport: nodeId, role: nodeData.role })
                    });
                    console.log('Added unique node:', nodeId);
                } else {
                    console.log('Skipping duplicate node:', nodeId);
                }
            } catch (error) {
                console.error('Error processing node data:', error);
            }
        });

        // Convert unique nodes map to array
        this.gData.nodes = Array.from(uniqueNodes.values());
        console.log('Total unique nodes:', this.gData.nodes.length);

        // Second pass: create links only between online nodes
        console.log('Creating graph with', this.gData.nodes.length, 'nodes');
        for (let i = 0; i < this.gData.nodes.length; i++) {
            const sourceNode = this.gData.nodes[i];
            const sourceIP = sourceNode.ip;
            
            // Skip if source node is offline
            if (this.offlineNodes.has(sourceIP)) {
                console.log('Skipping links for offline source node:', sourceIP);
                continue;
            }

            for (let j = i + 1; j < this.gData.nodes.length; j++) {
                const targetNode = this.gData.nodes[j];
                const targetIP = targetNode.ip;
                
                // Skip if target node is offline
                if (this.offlineNodes.has(targetIP)) {
                    console.log('Skipping link to offline target node:', targetIP);
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
        console.log('Initial data processing complete. Total links:', this.gData.links.length);
    }

    updateGraphData(data) {
        const nodeId = `${data.ip}:${data.port}`;
        console.log('Updating graph data for node:', nodeId);
        
        // Add or update node - ensure no duplication
        const existingNodeIndex = this.gData.nodes.findIndex(n => n.ipport === nodeId);
        if (existingNodeIndex === -1) {
            // Only add if node doesn't exist
            this.gData.nodes.push({
                id: data.idx,
                ip: data.ip,
                port: data.port,
                ipport: nodeId,
                role: data.role,
                color: this.getNodeColor({ ipport: nodeId, role: data.role })
            });
            console.log('Added new node:', nodeId);
        } else {
            // Update existing node
            this.gData.nodes[existingNodeIndex] = {
                ...this.gData.nodes[existingNodeIndex],
                role: data.role,
                color: this.getNodeColor({ ipport: nodeId, role: data.role })
            };
            console.log('Updated existing node:', nodeId);
        }

        // Normalize all existing links to use string IDs
        this.gData.links = this.gData.links.map(link => ({
            source: typeof link.source === 'object' ? link.source.ipport : link.source,
            target: typeof link.target === 'object' ? link.target.ipport : link.target,
            value: link.value
        }));

        // Store all existing links that don't involve this node
        const preservedLinks = this.gData.links.filter(link => 
            link.source !== nodeId && link.target !== nodeId
        );
        console.log('Preserved links:', preservedLinks);

        // Start with preserved links
        this.gData.links = [...preservedLinks];
        console.log('Links after preserving:', this.gData.links);

        // If node is offline, don't add any new links
        if (!data.status || this.offlineNodes.has(data.ip)) {
            console.log('Node is offline, not adding new links');
            return;
        }

        // Add links for this node's neighbors
        if (data.neighbors) {
            // Parse neighbors using consistent format
            const neighbors = data.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '');
            console.log('Processing neighbors:', neighbors);
            
            // Add new links only if both nodes are online
            neighbors.forEach(neighbor => {
                // Normalize neighbor ID to include port if not present
                const normalizedNeighbor = neighbor.includes(':') ? neighbor : `${neighbor}:${data.port}`;
                const neighborNode = this.gData.nodes.find(n => 
                    n.ipport === normalizedNeighbor || 
                    n.ipport.split(':')[0] === neighbor.split(':')[0]
                );

                // Skip if neighbor is offline
                if (this.offlineNodes.has(neighbor.split(':')[0])) {
                    console.log('Skipping link creation - neighbor is offline:', neighbor);
                    return;
                }

                if (neighborNode) {
                    console.log('Adding links between', nodeId, 'and', normalizedNeighbor);
                    
                    // Add link from this node to neighbor
                    this.gData.links.push({
                        source: nodeId,
                        target: normalizedNeighbor,
                        value: this.randomFloatFromInterval(1.0, 1.3)
                    });

                    // Add link from neighbor to this node (bidirectional)
                    this.gData.links.push({
                        source: normalizedNeighbor,
                        target: nodeId,
                        value: this.randomFloatFromInterval(1.0, 1.3)
                    });
                }
            });
        }

        // Remove duplicate links (in case they were added multiple times)
        this.gData.links = this.gData.links.filter((link, index, self) =>
            index === self.findIndex((l) => 
                (l.source === link.source && l.target === link.target) ||
                (l.source === link.target && l.target === link.source)
            )
        );

        console.log('Final links after update:', this.gData.links);
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
        // Check if the node is offline using the full IP:port
        if (this.offlineNodes.has(node.ipport)) {
            console.log('Node is offline:', node.ipport);
            return '#ff0000';
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

            // Get current neighbors before update
            const nodeId = `${data.ip}:${data.port}`;
            const currentLinks = this.gData.links.filter(link => 
                link.source === nodeId || link.target === nodeId
            );
            
            // Parse new neighbors
            const newNeighbors = data.neighbors 
                ? data.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                : [];
            
            // Find neighbors to remove (those in current links but not in new neighbors)
            const neighborsToRemove = currentLinks
                .map(link => {
                    const neighborId = link.source === nodeId ? link.target : link.source;
                    return neighborId.split(':')[0]; // Get just the IP part
                })
                .filter(neighborIP => !newNeighbors.includes(neighborIP));

            // Remove links to neighbors that are no longer in the list
            neighborsToRemove.forEach(neighborIP => {
                this.gData.links = this.gData.links.filter(link => {
                    const sourceIP = link.source.split(':')[0];
                    const targetIP = link.target.split(':')[0];
                    return !(sourceIP === neighborIP || targetIP === neighborIP);
                });
            });

            this.updateNode(data);
            // Update graph data with the new neighbors list
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

        const nodeId = `${data.ip}:${data.port}`;  // Use full IP:port as nodeId
        const wasOffline = this.offlineNodes.has(nodeId);
        const isNowOffline = !data.status;

        // Update offlineNodes set based on status
        if (isNowOffline) {
            this.offlineNodes.add(nodeId);
            console.log('Node marked as offline:', nodeId);
            
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
            console.log('Node marked as online:', nodeId);
            
            // Update marker appearance
            if (this.droneMarkers[data.uid]) {
                this.droneMarkers[data.uid].setIcon(this.droneIcon);
                this.droneMarkers[data.uid].getElement().classList.remove('drone-offline');
            }
        }

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
        console.log('Removing links for node:', nodeId);
        
        // Remove links from graph data
        const previousLinkCount = this.gData.links.length;
        
        // Remove all links where this node is either source or target
        this.gData.links = this.gData.links.filter(link => {
            const sourceId = typeof link.source === 'object' ? link.source.ipport : link.source;
            const targetId = typeof link.target === 'object' ? link.target.ipport : link.target;
            return sourceId !== nodeId && targetId !== nodeId;
        });
        
        console.log(`Removed ${previousLinkCount - this.gData.links.length} links for node ${nodeId}`);
        
        // Remove lines from map
        if (this.droneLines[data.uid]) {
            this.cleanupDroneLines(data.uid);
        }
        
        // Update any related lines from other nodes
        this.updateAllRelatedLines(data.uid);
    }

    updateGraph(data) {
        if (data) {
            // Update graph data with new node information
            this.updateGraphData(data);
        }
        
        // Filter out any links involving offline nodes
        this.gData.links = this.gData.links.filter(link => {
            const sourceId = typeof link.source === 'object' ? link.source.ipport : link.source;
            const targetId = typeof link.target === 'object' ? link.target.ipport : link.target;
            return !this.offlineNodes.has(sourceId) && !this.offlineNodes.has(targetId);
        });

        // Ensure all links have valid source and target nodes
        this.gData.links = this.gData.links.filter(link => {
            const sourceExists = this.gData.nodes.some(n => n.ipport === link.source);
            const targetExists = this.gData.nodes.some(n => n.ipport === link.target);
            return sourceExists && targetExists;
        });

        // Apply layout to nodes
        const layoutedNodes = this.layoutNodes([...this.gData.nodes]);
        
        // Update the graph with new data
        this.Graph.graphData({
            nodes: layoutedNodes,
            links: this.gData.links
        });

        // Reset the force simulation to ensure proper layout
        this.Graph.d3ReheatSimulation();
        
        // Force a redraw
        this.Graph.refresh();
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
            
            // Parse neighbors string into array, handling both space and comma separators
            const neighborsIPs = nodeData.neighbors 
                ? nodeData.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                : [];

            console.log('Parsed neighbor IPs:', neighborsIPs);

            // First update the marker
            console.log('Updating drone position for node:', nodeData.uid);
            this.updateDronePosition(
                nodeData.uid, 
                nodeData.ip, 
                lat, 
                lng, 
                neighborsIPs, 
                nodeData.neighbors_distance
            );

            // Then immediately update the lines for this node
            if (neighborsIPs.length > 0) {
                console.log('Updating neighbor lines for node:', nodeData.uid);
                this.updateNeighborLines(nodeData.uid, newLatLng, neighborsIPs, true);
            }

            // Finally update any related lines from other nodes
            this.updateAllRelatedLines(nodeData.uid);
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
                <p><strong>IP:</strong> ${ip}</p>
                <p><strong>Location:</strong> ${Number(lat).toFixed(4)}, ${Number(lng).toFixed(4)}</p>
                ${neighborIPs.length > 0 ? `<p><strong>Neighbors:</strong> ${neighborIPs.length}</p>` : ''}
            </div>`;

        if (!this.droneMarkers[droneId]) {
            console.log('Creating new marker for node:', droneId);
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
            console.log('Marker created and added to map:', marker);
        } else {
            console.log('Updating existing marker for node:', droneId);
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
            console.log('Marker updated:', this.droneMarkers[droneId]);
        }
    }

    updateNeighborLines(droneId, droneLatLng, neighborsIPs, condition) {
        console.log('Updating neighbor lines for drone:', droneId, 'with neighbors:', neighborsIPs);
        console.log('Current drone position:', droneLatLng);
        
        // Clean up existing lines for this drone
        this.cleanupDroneLines(droneId);

        if (!this.droneMarkers[droneId]) {
            console.warn('No marker found for drone:', droneId);
            return;
        }

        // Skip if current drone is offline
        if (this.offlineNodes.has(this.droneMarkers[droneId].ip)) {
            console.log('Skipping line creation - current drone is offline:', this.droneMarkers[droneId].ip);
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
                    console.log('Skipping line creation - neighbor is offline:', neighborIPOnly);
                    return;
                }

                console.log('Found neighbor marker for IP:', neighborIPOnly);
                const neighborLatLng = neighborMarker.getLatLng();
                console.log('Neighbor position:', neighborLatLng);
                
                console.log('Creating line between:', droneLatLng, 'and', neighborLatLng);
                
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
                        const distance = condition 
                            ? (this.droneMarkers[droneId].neighbors_distance && 
                               this.droneMarkers[droneId].neighbors_distance[neighborIP])
                            : (neighborMarker.neighbors_distance && 
                               neighborMarker.neighbors_distance[this.droneMarkers[droneId].ip]);
                        
                        line.bindPopup(`
                            <div class="line-popup">
                                <p><strong>Distance:</strong> ${distance ? distance + ' m' : 'Calculating...'}</p>
                                <p><strong>Status:</strong> Online</p>
                            </div>
                        `);
                    } catch (err) {
                        console.warn('Error binding popup to line:', err);
                        line.bindPopup('Distance: Calculating...');
                    }

                    // Add hover behavior
                    line.on('mouseover', function() {
                        this.openPopup();
                    });

                    // Add the line to the layer group
                    this.lineLayer.addLayer(line);
                    console.log('Line added to line layer');

                    // Store the line
                    this.droneLines[droneId].push(line);
                    console.log('Line stored in droneLines array');

                } catch (error) {
                    console.error('Error creating/adding line:', error);
                }
            } else {
                console.warn('No marker found for neighbor IP:', neighborIPOnly);
            }
        });
    }

    cleanupDroneLines(droneId) {
        console.log('Cleaning up lines for drone:', droneId);
        if (this.droneLines[droneId]) {
            this.droneLines[droneId].forEach(line => {
                if (line) {
                    try {
                        // Remove from layer group
                        this.lineLayer.removeLayer(line);
                        console.log('Line removed from layer');
                    } catch (error) {
                        console.error('Error removing line:', error);
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
            console.warn('No IP found for drone:', droneId);
            return;
        }

        console.log('Updating related lines for drone:', droneId, 'with IP:', currentDroneIP);

        // Update lines for all drones that have this drone as a neighbor
        Object.entries(this.droneMarkers).forEach(([id, marker]) => {
            if (id !== droneId && marker.neighbors) {
                console.log('Processing marker:', id, 'with neighbors:', marker.neighbors, 'type:', typeof marker.neighbors);
                
                // Handle both string and array formats for neighbors
                const neighborIPs = Array.isArray(marker.neighbors) 
                    ? marker.neighbors 
                    : (typeof marker.neighbors === 'string' 
                        ? marker.neighbors.split(/[\s,]+/).filter(ip => ip.trim() !== '')
                        : []);
                
                console.log('Processed neighbor IPs:', neighborIPs);
                
                if (neighborIPs.some(ip => ip.startsWith(currentDroneIP))) {
                    console.log('Found matching neighbor, updating lines');
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
        console.log('Looking for marker with IP:', ipOnly);
        console.log('Available markers:', Object.values(this.droneMarkers).map(m => m.ip));
        
        const marker = Object.values(this.droneMarkers).find(marker => {
            const markerIP = marker.ip.split(':')[0];
            const matches = markerIP === ipOnly;
            if (matches) {
                console.log('Found matching marker:', markerIP);
            }
            return matches;
        });
        
        if (!marker) {
            console.warn('No marker found for IP:', ipOnly);
        }
        return marker;
    }
}

// Initialize monitor when DOM is loaded
document.addEventListener('DOMContentLoaded', () => {
    new Monitor();
}); 