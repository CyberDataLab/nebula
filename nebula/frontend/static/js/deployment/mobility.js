// Mobility Configuration Module
const MobilityManager = {
    map: null,

    initializeMobility() {
        this.setupLocationControls();
        this.setupMobilityControls();
        this.setupAdditionalParticipants();
    },

    setupLocationControls() {
        const customLocationDiv = document.getElementById("mobility-custom-location");
        
        document.getElementById("random-geo-btn").addEventListener("click", () => {
            customLocationDiv.style.display = "none";
        });

        document.getElementById("custom-location-btn").addEventListener("click", () => {
            customLocationDiv.style.display = "block";
        });

        document.getElementById("current-location-btn").addEventListener("click", () => {
            navigator.geolocation.getCurrentPosition(position => {
                document.getElementById("latitude").value = position.coords.latitude;
                document.getElementById("longitude").value = position.coords.longitude;
                if (this.map) {
                    this.updateMapMarker(position.coords.latitude, position.coords.longitude);
                }
            });
        });

        document.getElementById("open-map-btn").addEventListener("click", () => {
            const mapContainer = document.getElementById("map-container");
            if (mapContainer.style.display === "none") {
                mapContainer.style.display = "block";
                this.initializeMap();
            } else {
                mapContainer.style.display = "none";
            }
        });
    },

    setupMobilityControls() {
        const mobilityOptionsDiv = document.getElementById("mobility-options");
        
        document.getElementById("without-mobility-btn").addEventListener("click", () => {
            mobilityOptionsDiv.style.display = "none";
            if (this.map) {
                this.removeMapCircle();
            }
        });

        document.getElementById("mobility-btn").addEventListener("click", () => {
            mobilityOptionsDiv.style.display = "block";
            if (this.map) {
                this.updateMapCircle();
            }
        });

        document.getElementById("radiusFederation").addEventListener("change", () => {
            if (this.map && document.getElementById("mobility-btn").checked) {
                this.updateMapCircle();
            }
        });
    },

    initializeMap() {
        if (!this.map) {
            this.map = L.map('map').setView([38.023522, -1.174389], 17);
            
            L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}', {
                attribution: '&copy; <a href="https://enriquetomasmb.com">enriquetomasmb.com</a>',
                maxZoom: 18,
            }).addTo(this.map);

            this.addInitialMarker();
            if (document.getElementById("mobility-btn").checked) {
                this.addMapCircle();
            }

            this.map.on('click', this.handleMapClick.bind(this));
        }
    },

    addInitialMarker() {
        const lat = parseFloat(document.getElementById("latitude").value);
        const lng = parseFloat(document.getElementById("longitude").value);
        this.updateMapMarker(lat, lng);
    },

    handleMapClick(e) {
        this.updateMapMarker(e.latlng.lat, e.latlng.lng);
        document.getElementById("latitude").value = e.latlng.lat;
        document.getElementById("longitude").value = e.latlng.lng;
    },

    updateMapMarker(lat, lng) {
        this.map.eachLayer(layer => {
            if (layer instanceof L.Marker) {
                this.map.removeLayer(layer);
            }
        });
        L.marker([lat, lng]).addTo(this.map);
        this.updateMapCircle();
    },

    addMapCircle() {
        const lat = parseFloat(document.getElementById("latitude").value);
        const lng = parseFloat(document.getElementById("longitude").value);
        const radius = parseInt(document.getElementById("radiusFederation").value);

        L.circle([lat, lng], {
            color: 'red',
            fillColor: '#f03',
            fillOpacity: 0.4,
            radius: radius
        }).addTo(this.map);
    },

    updateMapCircle() {
        this.removeMapCircle();
        if (document.getElementById("mobility-btn").checked) {
            this.addMapCircle();
        }
    },

    removeMapCircle() {
        this.map.eachLayer(layer => {
            if (layer instanceof L.Circle) {
                this.map.removeLayer(layer);
            }
        });
    },

    setupAdditionalParticipants() {
        document.getElementById("additionalParticipants").addEventListener("change", function() {
            const container = document.getElementById("additional-participants-items");
            container.innerHTML = "";

            for (let i = 0; i < this.value; i++) {
                const participantItem = this.createParticipantItem(i);
                container.appendChild(participantItem);
            }
        }.bind(this));
    },

    createParticipantItem(index) {
        const participantItem = document.createElement("div");
        participantItem.style.marginLeft = "20px";
        participantItem.classList.add("additional-participant-item");

        const heading = document.createElement("h5");
        heading.textContent = `Round of deployment (participant ${index + 1})`;
        
        const input = document.createElement("input");
        input.type = "number";
        input.classList.add("form-control");
        input.id = `roundsAdditionalParticipant${index}`;
        input.placeholder = "round";
        input.min = "1";
        input.value = "1";
        input.style.display = "inline";
        input.style.width = "20%";

        participantItem.appendChild(heading);
        participantItem.appendChild(input);

        return participantItem;
    },

    getMobilityConfig() {
        const config = {
            enabled: document.getElementById("mobility-btn").checked,
            randomGeo: document.getElementById("random-geo-btn").checked,
            location: {
                latitude: parseFloat(document.getElementById("latitude").value),
                longitude: parseFloat(document.getElementById("longitude").value)
            },
            mobilityType: document.getElementById("mobilitySelect").value,
            radiusFederation: parseInt(document.getElementById("radiusFederation").value),
            schemeMobility: document.getElementById("schemeMobilitySelect").value,
            roundFrequency: parseInt(document.getElementById("roundFrequency").value),
            mobileParticipantsPercent: parseInt(document.getElementById("mobileParticipantsPercent").value),
            additionalParticipants: []
        };

        const additionalParticipantsCount = parseInt(document.getElementById("additionalParticipants").value);
        for (let i = 0; i < additionalParticipantsCount; i++) {
            config.additionalParticipants.push({
                round: parseInt(document.getElementById(`roundsAdditionalParticipant${i}`).value)
            });
        }

        return config;
    },

    setMobilityConfig(config) {
        if (!config) return;

        // Validate required properties
        if (typeof config.enabled !== 'boolean') {
            console.warn('Invalid mobility config: enabled must be a boolean');
            return;
        }

        if (typeof config.randomGeo !== 'boolean') {
            console.warn('Invalid mobility config: randomGeo must be a boolean');
            return;
        }

        if (config.location && (typeof config.location.latitude !== 'number' || typeof config.location.longitude !== 'number')) {
            console.warn('Invalid mobility config: location must have numeric latitude and longitude');
            return;
        }

        // Set mobility enabled/disabled
        document.getElementById("mobility-btn").checked = config.enabled;
        document.getElementById("without-mobility-btn").checked = !config.enabled;
        document.getElementById("mobility-options").style.display = config.enabled ? "block" : "none";

        // Set location type and coordinates
        document.getElementById("random-geo-btn").checked = config.randomGeo;
        document.getElementById("custom-location-btn").checked = !config.randomGeo;
        document.getElementById("mobility-custom-location").style.display = config.randomGeo ? "none" : "block";
        
        if (config.location) {
            document.getElementById("latitude").value = config.location.latitude;
            document.getElementById("longitude").value = config.location.longitude;
            if (this.map) {
                this.updateMapMarker(config.location.latitude, config.location.longitude);
            }
        }

        // Set mobility settings
        document.getElementById("mobilitySelect").value = config.mobilityType || "both";
        document.getElementById("radiusFederation").value = config.radiusFederation || 100;
        document.getElementById("schemeMobilitySelect").value = config.schemeMobility || "random";
        document.getElementById("roundFrequency").value = config.roundFrequency || 1;
        document.getElementById("mobileParticipantsPercent").value = config.mobileParticipantsPercent || 100;

        // Set additional participants
        if (config.additionalParticipants) {
            if (!Array.isArray(config.additionalParticipants)) {
                console.warn('Invalid mobility config: additionalParticipants must be an array');
                return;
            }

            document.getElementById("additionalParticipants").value = config.additionalParticipants.length;
            const container = document.getElementById("additional-participants-items");
            container.innerHTML = "";

            config.additionalParticipants.forEach((participant, index) => {
                if (typeof participant.round !== 'number') {
                    console.warn(`Invalid mobility config: participant ${index} round must be a number`);
                    return;
                }
                const participantItem = this.createParticipantItem(index);
                document.getElementById(`roundsAdditionalParticipant${index}`).value = participant.round;
                container.appendChild(participantItem);
            });
        }
    },

    resetMobilityConfig() {
        // Reset to default values
        document.getElementById("without-mobility-btn").checked = true;
        document.getElementById("mobility-options").style.display = "none";
        document.getElementById("random-geo-btn").checked = false;
        document.getElementById("custom-location-btn").checked = true;
        document.getElementById("mobility-custom-location").style.display = "block";
        document.getElementById("latitude").value = "38.023522";
        document.getElementById("longitude").value = "-1.174389";
        document.getElementById("mobilitySelect").value = "both";
        document.getElementById("radiusFederation").value = "100";
        document.getElementById("schemeMobilitySelect").value = "random";
        document.getElementById("roundFrequency").value = "1";
        document.getElementById("mobileParticipantsPercent").value = "100";
        document.getElementById("additionalParticipants").value = "0";
        document.getElementById("additional-participants-items").innerHTML = "";

        if (this.map) {
            this.updateMapMarker(38.023522, -1.174389);
            this.removeMapCircle();
        }
    }
};

export default MobilityManager; 