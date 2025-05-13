// Help Content Module
const HelpContent = (function() {
    function initializePopovers() {
        const tooltipElements = {
            'processHelpIcon': 'Process deployment allows you to deploy participants in the same machine using different processes.',
            'dockerHelpIcon': 'Docker deployment allows you to deploy participants in different containers.',
            'architectureHelpIcon': architecture,
            'topologyCustomIcon': topology.custom,
            'topologyPredefinedIcon': topology.predefined,
            'datasetHelpIcon': dataset,
            'iidHelpIcon': iid,
            'partitionMethodsHelpIcon': partitionMethods,
            'parameterSettingHelpIcon': parameterSetting,
            'modelHelpIcon': model,
            'maliciousHelpIcon': malicious
        };

        Object.entries(tooltipElements).forEach(([id, content]) => {
            const element = document.getElementById(id);
            if (element) {
                new bootstrap.Tooltip(element, {
                    title: content,
                    html: true,
                    placement: 'right'
                });
            }
        });
    }

    const topology = {
        custom: `<div style="text-align: left;">
            <strong>Custom Topology</strong>
            <ul style="margin-bottom: 0;">
                <li>Custom: Custom topology with the nodes</li>
            </ul>
        </div>`,
        predefined: `<div style="text-align: left;">
            <strong>Predefined Topologies</strong>
            <ul style="margin-bottom: 0;">
                <li>Fully: All nodes are connected to all other nodes</li>
                <li>Ring: All nodes are connected to two other nodes</li>
                <li>Star: A central node is connected to all other nodes</li>
                <li>Random: Nodes are connected to random nodes</li>
            </ul>
        </div>`
    };

    const architecture = `<div style="text-align: left;">
        <strong>Federation Architectures</strong>
        <ul style="margin-bottom: 0;">
            <li>CFL: All nodes are connected to a central node</li>
            <li>DFL: Nodes are connected to each other</li>
            <li>SDFL: Nodes are connected to each other and the aggregator rotates</li>
        </ul>
    </div>`;

    const dataset = `<div style="text-align: left;">
        <strong>Available Datasets</strong>
        <ul style="margin-bottom: 0;">
            <li>MNIST: The MNIST dataset</li>
            <li>FashionMNIST: The FashionMNIST dataset</li>
            <li>CIFAR10: The CIFAR10 dataset</li>
        </ul>
    </div>`;

    const iid = `<div style="text-align: left;">
        <strong>Data Distribution Types</strong>
        <ul style="margin-bottom: 0;">
            <li><strong>IID</strong> (Independent and Identically Distributed):
                <ul>
                    <li>Each participant has a complete set of categories</li>
                    <li>Equal number of samples per category within each participant</li>
                </ul>
            </li>
            <li><strong>Non-IID</strong> (Non-independent and Identically Distributed):
                <ul>
                    <li>Data distribution does not meet IID conditions</li>
                    <li>May have missing categories or uneven sample distribution</li>
                </ul>
            </li>
        </ul>
    </div>`;

    const partitionMethods = `<div style="text-align: left;">
        <strong>Partition Methods</strong>
        <ul style="margin-bottom: 0;">
            <li><strong>Dirichlet:</strong> Partition using a Dirichlet distribution</li>
            <li><strong>Percentage:</strong> Partition with specified non-IID level</li>
            <li><strong>BalancedIID:</strong> Equal-sized IID partitions</li>
            <li><strong>UnbalancedIID:</strong> Varying-sized IID partitions</li>
        </ul>
    </div>`;

    const parameterSetting = `<div style="text-align: left;">
        <strong>Parameter Settings</strong>
        <ul style="margin-bottom: 0;">
            <li><strong>Dirichlet:</strong>
                <ul>
                    <li>Parameter: alpha (float)</li>
                    <li>Lower value = greater imbalance</li>
                </ul>
            </li>
            <li><strong>Percentage:</strong>
                <ul>
                    <li>Parameter: percentage (10-100)</li>
                    <li>Controls non-IID level</li>
                    <li>Lower value = greater imbalance</li>
                </ul>
            </li>
            <li><strong>UnbalancedIID:</strong>
                <ul>
                    <li>Parameter: imbalance_factor (>1)</li>
                    <li>Controls dataset size imbalance</li>
                </ul>
            </li>
        </ul>
    </div>`;

    const model = `<div style="text-align: left;">
        <strong>Available Models</strong>
        <ul style="margin-bottom: 0;">
            <li>MLP: Multi-layer perceptron</li>
            <li>CNN: Convolutional neural network</li>
            <li>RNN: Recurrent neural network</li>
        </ul>
    </div>`;

    const malicious = `<div style="text-align: left;">
        <strong>Malicious Node Selection</strong>
        <ul style="margin-bottom: 0;">
            <li><strong>Percentage:</strong> Set percentage of malicious nodes</li>
            <li><strong>Manual:</strong> Select malicious nodes in the graph</li>
        </ul>
    </div>`;

    const deployment = {
        process: `<div style="text-align: left;">
            <strong>Process Deployment</strong>
            <ul style="margin-bottom: 0;">
                <li>Deploy federation nodes using processes</li>
            </ul>
        </div>`,
        docker: `<div style="text-align: left;">
            <strong>Docker Deployment</strong>
            <ul style="margin-bottom: 0;">
                <li>Deploy federation nodes using docker containers</li>
            </ul>
        </div>`
    };

    const reputation = {
        initialization: `<div style="text-align: left;">
            <strong>Reputation Initialization</strong>
            <p style="margin-bottom: 0;">Initial reputation value for all participants</p>
        </div>`,
        weighting: `<div style="text-align: left;">
            <strong>Weighting Factor</strong>
            <p style="margin-bottom: 0;">Use dynamic or static weighting factor for reputation</p>
        </div>`
    };

    return {
        initializePopovers,
        topology,
        architecture,
        dataset,
        iid,
        partitionMethods,
        parameterSetting,
        model,
        malicious,
        deployment,
        reputation
    };
})();

export default HelpContent; 