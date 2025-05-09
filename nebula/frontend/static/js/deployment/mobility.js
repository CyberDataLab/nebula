// Mobility Configuration Module
const MobilityManager = (function() {
    let map = null;

    function initializeMobility() {
        setupLocationControls();
        setupMobilityControls();
        setupAdditionalParticipants();
    }

    function setupLocationControls() {
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
                if (map) {
                    updateMapMarker(position.coords.latitude, position.coords.longitude);
                }
            });
        });

        document.getElementById("open-map-btn").addEventListener("click", () => {
            const mapContainer = document.getElementById("map-container");
            if (mapContainer.style.display === "none") {
                mapContainer.style.display = "block";
                initializeMap();
            } else {
                mapContainer.style.display = "none";
            }
        });
    }

    function setupMobilityControls() {
        const mobilityOptionsDiv = document.getElementById("mobility-options");
        
        document.getElementById("without-mobility-btn").addEventListener("click", () => {
            mobilityOptionsDiv.style.display = "none";
            if (map) {
                removeMapCircle();
            }
        });

        document.getElementById("mobility-btn").addEventListener("click", () => {
            mobilityOptionsDiv.style.display = "block";
            if (map) {
                addMapCircle();
            }
        });

        document.getElementById("radiusFederation").addEventListener("change", () => {
            if (map && document.getElementById("mobility-btn").checked) {
                updateMapCircle();
            }
        });
    }

    function initializeMap() {
        if (!map) {
            map = L.map('map').setView([38.023522, -1.174389], 13);
            
            L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
                attribution: '&copy; <a href="https://enriquetomasmb.com">enriquetomasmb.com</a>',
                maxZoom: 18,
            }).addTo(map);

            addInitialMarker();
            if (document.getElementById("mobility-btn").checked) {
                addMapCircle();
            }

            map.on('click', handleMapClick);
        }
    }

    function addInitialMarker() {
        const lat = parseFloat(document.getElementById("latitude").value);
        const lng = parseFloat(document.getElementById("longitude").value);
        updateMapMarker(lat, lng);
    }

    function handleMapClick(e) {
        updateMapMarker(e.latlng.lat, e.latlng.lng);
        document.getElementById("latitude").value = e.latlng.lat;
        document.getElementById("longitude").value = e.latlng.lng;
    }

    function updateMapMarker(lat, lng) {
        map.eachLayer(layer => {
            if (layer instanceof L.Marker) {
                map.removeLayer(layer);
            }
        });
        L.marker([lat, lng]).addTo(map);
        updateMapCircle();
    }

    function addMapCircle() {
        const lat = parseFloat(document.getElementById("latitude").value);
        const lng = parseFloat(document.getElementById("longitude").value);
        const radius = parseInt(document.getElementById("radiusFederation").value);

        L.circle([lat, lng], {
            color: 'red',
            fillColor: '#f03',
            fillOpacity: 0.4,
            radius: radius
        }).addTo(map);
    }

    function updateMapCircle() {
        removeMapCircle();
        if (document.getElementById("mobility-btn").checked) {
            addMapCircle();
        }
    }

    function removeMapCircle() {
        map.eachLayer(layer => {
            if (layer instanceof L.Circle) {
                map.removeLayer(layer);
            }
        });
    }

    function setupAdditionalParticipants() {
        document.getElementById("additionalParticipants").addEventListener("change", function() {
            const container = document.getElementById("additional-participants-items");
            container.innerHTML = "";

            for (let i = 0; i < this.value; i++) {
                const participantItem = createParticipantItem(i);
                container.appendChild(participantItem);
            }
        });
    }

    function createParticipantItem(index) {
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
    }

    function getMobilityConfig() {
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
    }

    function setMobilityConfig(config) {
        if (!config) return;

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
            if (map) {
                updateMapMarker(config.location.latitude, config.location.longitude);
            }
        }

        // Set mobility settings
        document.getElementById("mobilitySelect").value = config.mobilityType || "both";
        document.getElementById("radiusFederation").value = config.radiusFederation || 1000;
        document.getElementById("schemeMobilitySelect").value = config.schemeMobility || "random";
        document.getElementById("roundFrequency").value = config.roundFrequency || 1;
        document.getElementById("mobileParticipantsPercent").value = config.mobileParticipantsPercent || 100;

        // Set additional participants
        if (config.additionalParticipants) {
            document.getElementById("additionalParticipants").value = config.additionalParticipants.length;
            const container = document.getElementById("additional-participants-items");
            container.innerHTML = "";

            config.additionalParticipants.forEach((participant, index) => {
                const participantItem = createParticipantItem(index);
                document.getElementById(`roundsAdditionalParticipant${index}`).value = participant.round;
                container.appendChild(participantItem);
            });
        }
    }

    function resetMobilityConfig() {
        // Reset to default values
        document.getElementById("without-mobility-btn").checked = true;
        document.getElementById("mobility-options").style.display = "none";
        document.getElementById("random-geo-btn").checked = true;
        document.getElementById("mobility-custom-location").style.display = "none";
        document.getElementById("latitude").value = "38.023522";
        document.getElementById("longitude").value = "-1.174389";
        document.getElementById("mobilitySelect").value = "both";
        document.getElementById("radiusFederation").value = "1000";
        document.getElementById("schemeMobilitySelect").value = "random";
        document.getElementById("roundFrequency").value = "1";
        document.getElementById("mobileParticipantsPercent").value = "100";
        document.getElementById("additionalParticipants").value = "0";
        document.getElementById("additional-participants-items").innerHTML = "";

        if (map) {
            updateMapMarker(38.023522, -1.174389);
            removeMapCircle();
        }
    }

    return {
        initializeMobility,
        getMap: () => map,
        getMobilityConfig,
        setMobilityConfig,
        resetMobilityConfig
    };
})();

export default MobilityManager; 