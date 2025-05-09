// Help Content Module
const HelpContent = (function() {
    function initializePopovers() {
        const tooltipElements = {
            'processHelpIcon': 'Process deployment allows you to deploy participants in the same machine using different processes.',
            'dockerHelpIcon': 'Docker deployment allows you to deploy participants in different containers.',
            'architectureHelpIcon': topology.predefined,
            'topologyCustomIcon': topology.custom,
            'topologyPredefinedIcon': topology.predefined,
            'datasetHelpIcon': 'Select the dataset to be used in the federation.',
            'iidHelpIcon': 'IID data is identically distributed among participants. Non-IID data is not identically distributed.',
            'partitionMethodsHelpIcon': 'Method to distribute the data among participants.',
            'parameterSettingHelpIcon': 'Parameter for the selected partition method.',
            'modelHelpIcon': 'Select the model to be used in the federation.',
            'maliciousHelpIcon': 'Select malicious nodes manually by right-clicking on them.'
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
        custom: `<ul>
            <li>Custom: Custom topology with the nodes</li>
        </ul>`,
        predefined: `<ul>
            <li>Fully: All nodes are connected to all other nodes</li>
            <li>Ring: All nodes are connected to two other nodes</li>
            <li>Star: A central node is connected to all other nodes</li>
            <li>Random: Nodes are connected to random nodes</li>
        </ul>`
    };

    const architecture = `<ul>
        <li>CFL: All nodes are connected to a central node</li>
        <li>DFL: Nodes are connected to each other</li>
        <li>SDFL: Nodes are connected to each other and the aggregator rotates</li>
    </ul>`;

    const dataset = `<ul>
        <li>MNIST: The MNIST dataset</li>
        <li>FashionMNIST: The FashionMNIST dataset</li>
        <li>CIFAR10: The CIFAR10 dataset</li>
    </ul>`;

    const iid = `<ul>
        <li>IID: Independent and identically distributed</li>
        <li>IID must satisfy two conditions:</li>
        <ul>
            <li>(1) Each participant possesses a complete set of categories.</li>
            <li>(2) The number of samples for each category within each participant is equal.</li>
        </ul>
        <li>Non-IID: Non-independent and identically distributed</li>
        <li>If any of the above two conditions are not met, it is considered as non-IID.</li>
    </ul>`;

    const partitionMethods = `<ul>
        <li>Dirichlet: Partition the dataset into multiple subsets using a Dirichlet distribution.</li>
        <li>Percentage: Partition the dataset into multiple subsets with a specified level of non-IID-ness.</li>
        <li>BalancedIID: Partition the dataset into multiple subsets with equal sizes in an IID manner.</li>
        <li>UnbalancedIId: Partition the dataset into multiple subsets with varying sizes in an IID manner.</li>
    </ul>`;

    const parameterSetting = `<ul>
        <li>Dirichlet: alpha (float): The concentration parameter of the Dirichlet distribution. The lower the value, the greater the imbalance.</li>
        <li>Percentage: percentage (int): A value between 10 and 100 that specifies the desired level of non-IID-ness for the labels of the federated data. This percentage controls the imbalance in the class distribution across different subsets. The lower the value, the greater the imbalance.</li>
        <li>UnbalancedIId: imbalance_factor (float): A value over 1 that controls the imbalance of size of dataset among the subsets. The lower the value, the greater the imbalance.</li>
    </ul>`;

    const model = `<ul>
        <li>MLP: Multi-layer perceptron</li>
        <li>CNN: Convolutional neural network</li>
        <li>RNN: Recurrent neural network</li>
    </ul>`;

    const malicious = `<ul>
        <li>Percentage: Set the percentage of malicious nodes</li>
        <li>Manual: Select malicious nodes in the graph</li>
    </ul>`;

    const deployment = {
        process: `<ul>
            <li>Processes: Deploy the nodes of the federation using processes</li>
        </ul>`,
        docker: `<ul>
            <li>Docker: Deploy the nodes of the federation using docker containers</li>
        </ul>`
    };

    const reputation = {
        initialization: "Initial reputation value for all participants",
        weighting: "Use dynamic or static weighting factor for reputation"
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