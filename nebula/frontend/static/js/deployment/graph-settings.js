// Graph Settings Module
const GraphSettings = (function() {
    const Settings = {
        solidDistance: 50,
        Distance: 50
    };

    function initializeDistanceControls() {
        const distanceInput = document.getElementById('distanceInput');
        const distanceValue = document.getElementById('distanceValue');

        distanceInput.addEventListener('input', function() {
            distanceValue.value = distanceInput.value;
            Settings.Distance = distanceInput.value;
            updateLinkDistance();
        });

        distanceValue.addEventListener('input', function() {
            distanceInput.value = distanceValue.value;
            Settings.Distance = distanceValue.value;
            updateLinkDistance();
        });
    }

    function updateLinkDistance() {
        const Graph = window.TopologyManager.getGraph();
        if (Graph) {
            Graph.d3Force('link')
                .distance(link => link.color ? Settings.solidDistance : Settings.Distance);
            Graph.numDimensions(3); // Re-heat simulation
        }
    }

    return {
        initializeDistanceControls,
        updateLinkDistance,
        getSettings: () => Settings
    };
})();

export default GraphSettings;
