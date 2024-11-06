// SPDX-License-Identifier: MIT
pragma solidity 0.8.22;
// EVM-Version => PARIS, otherwise it will not work properly!

contract ReputationSystem {

    constructor() payable {}

    // object placed in every cell of the adjacency matrix
    struct Edge {
        // bool, set to true if node in ajd_matrix confirmed the other node as neighbour
        bool neighbour;

        // list of all pushed opinions
        uint64[] opinions;
    }

    struct Node {
        // ip:port defined by NEBULA
        string name;

        // public wallet address
        address account;

        // index in nodes list for fast access
        uint index;

        // state, if node has already registered itself
        bool registered;

        // state, if node was already registered as neighbour by any node
        bool in_adj;
    }

    // general object to simplify returning dicts to requester
    struct Dict {
        string key;
        uint64 value;
    }

    struct Stats_Dict {
        // ip:port from NEBULA
        string name;

        // unscaled averaged reputation
        uint64 reputation;

        // weighted reputation, decreased by directed opinion of requesting node
        uint64 weighted_reputation;

        // number of stddev away from median
        uint64 stddev_count;

        // divisor, for reducing the reputation because of suspected poisoning
        uint64 divisor;

        // reduced reputation, adapted to suspected poisoning
        uint64 final_reputation;

        // average of all unscaled reputations
        uint64 avg;

        // median of all unscaled reputations
        uint64 median;

        // standard deviation of all unscaled reputations
        uint64 stddev;

        // index in nodes list for fas access
        uint index;

        // standard deviations of opinion between node and all other nodes
        // nodes should approximately agree on their relative similarities
        uint64 avg_difference_opinions;

        // average of all average differences of opinions
        uint64 avg_avg_difference_opinions;

        // 1 if node was assessed to report highly deviating opinions
        // 0 if difference of local view and neighbors' views is low
        uint64 malicious_opinions;
    }

    // scale all values up to reduce error due to missing floats in solidity
    uint64 MULTIPLIER = 1000000;

    // participating nodes of FL scenario
    Node[] private nodes;

    // hash tables, for fast access of Nodes
    mapping(address => Node) private accounts;
    mapping(string => Node) private names;

    // adjacency matrix of reputation system
    // ordered by index of participants list
    Edge[][] private adj_matrix;

    function register(string memory name) external returns (bool) {

        // check if participant was registered as neighbour before
        Node storage node = names[name];

        require(node.registered == false, "Node is already registered.");

        // check if node was already created as neighbour
        if (node.in_adj){

            // if node was partially registered as neighbour
            // complete setting up node's information
            node.account = msg.sender;
            node.registered = true;
            accounts[msg.sender] = node;
            names[name] = node;
            nodes[node.index] = node;

        } else {

            // if node is not not known to the contract, set up completely
            node.name = name;
            node.account = msg.sender;
            node.index = nodes.length;
            node.registered = true;
            node.in_adj = false;

            // add node to hash tables
            accounts[msg.sender] = node;
            names[name] = node;

            // push node to list of participants
            nodes.push(node);
        }
        return true;
    }

    function register_neighbours(Dict[] memory neighbours, string memory name ) private returns (bool) {

        // retrieve registered node of method caller
        Node memory node = names[name];

        // check for each neighbour if it was already discovered by someone else
        for (uint64 i=0; i<neighbours.length; i++){

            string memory neighbour_name = neighbours[i].key;

            // skip empty neighbour names
            if (bytes(neighbour_name).length == 0){
                continue;
            }

            // partially setup neighbour as participant
            Node storage neighbour = names[neighbour_name];

            // check if newly discovered neighbour did already register itself
            if (neighbour.registered == false){

                // discovered neighbour is completely unknown to the chain code
                // initialize all parameters
                neighbour.name = neighbour_name;
                neighbour.index = nodes.length;
                neighbour.in_adj = true;

                // add neighbour to hash table
                names[neighbour_name] = neighbour;

                // push neighbour to list of participants
                nodes.push(neighbour);
            }
            else if (neighbour.in_adj == false){

                // neighbour is known to the chain code but not yet in the adj_matrix
                // update neighbour in hash tables
                neighbour.in_adj = true;
                names[neighbour_name] = neighbour;
                accounts[neighbour.account] = neighbour;
                nodes[neighbour.index] = neighbour;
            }
        }

        // increase the y dimension of the existing adj_matrix's columns
        while (adj_matrix.length < nodes.length){
            adj_matrix.push();
        }

        // increase the x dimension of the existing adj_matrix's rows
        for (uint64 y=0; y<adj_matrix.length; y++){

            while (adj_matrix[y].length < nodes.length){
                adj_matrix[y].push(Edge(false, new uint64[](0)));
            }
        }

        // register all neighbours for msg.sender
        for (uint64 j=0; j<neighbours.length; j++){

            // get column index of neighbour
            uint neighbour_index = names[neighbours[j].key].index;

            // set Edge to neighbour of calling node
            adj_matrix[node.index][neighbour_index].neighbour = true;
        }

        return true;
    }

    function rate_neighbours(Dict[] memory neighbours) public returns (bool){

        // check if msg.sender did register itself before using the reputation system
        require(accounts[msg.sender].registered, "msg.sender did not register itself");

        // retrieve sender's node from participants list
        uint index_sender = accounts[msg.sender].index;

        // add all nodes to the adjacency matrix which are not yet discovered
        register_neighbours(neighbours, accounts[msg.sender].name);

        // iterate over all neighbours
        for (uint64 i=0; i<neighbours.length; i++){

            // check if node was already discovered by other nodes
            Dict memory neighbour = neighbours[i];

            // if local opinion about other node is 0 or node did not register
            if (
                // skip nodes which are not in the adj_matrix
                names[neighbour.key].in_adj == false
            ){
                continue;
            }

            require(neighbour.value <= 100, "Opinion should be less than or equal to 100");
            require(neighbour.value >= 0, "Opinion should be greater than or equal to 0");

            // retrieve indexes in nodes list for accessing adjacency matrix
            uint index_target = names[neighbour.key].index;

            // access cell in adj_matrix for pushing the latest opinion
            Edge storage edge = adj_matrix[index_sender][index_target];

            // storing 0 results in various branches during statistical computations
            // storing 1 instead of 0 reduces the complexity by loosing only minor precision
            // uint64 non_zero_opinion = neighbour.value > 0 ? neighbour.value : 1;

            // push opinion value to Edge object in adj_matrix
            edge.opinions.push(neighbour.value);
        }

        return true;
    }

    function confirm_registration() public view returns(bool){

        // check if node did register itself with its public address
        return accounts[msg.sender].registered;
    }

    function confirmed_neighbours(uint node_a, uint node_b) private view returns (bool){

        // check adjacency matrix if both nodes did discover each other
        return adj_matrix[node_a][node_b].neighbour && adj_matrix[node_b][node_a].neighbour && node_a != node_b;
    }

    function avg_difference_to_neighbours(uint node_index) private view returns (uint64){

        // store sum of all avg differences between a node and all its valid neighbours
        uint64 sum_differences;
        uint64 n_confirmed_neighbours;

        for (uint64 neighbor_index=0; neighbor_index<nodes.length; neighbor_index++){

            // only trust edges between nodes which were confirmed by both nodes
            if (confirmed_neighbours(node_index, neighbor_index) == false){
                continue;
            }

            // retrieve the nodes' opinion history about each other
            uint64[] memory opinions_node = adj_matrix[node_index][neighbor_index].opinions;
            uint64[] memory opinions_neighbour = adj_matrix[neighbor_index][node_index].opinions;

            // if one of the nodes did not push any opinions yet, there is no deviation
            // if the number of stored opinions differs by a lot, the difference is not relevant anymore
            // skip very first opinion to wait for network to become more in sync before detecting anomalies
            if (
                opinions_node.length < 2 ||
                opinions_neighbour.length < 2 ||
                abs(int64(uint64(opinions_node.length)) - int64(uint64(opinions_neighbour.length))) > 2

            ){
                continue;
            }

            // sum up the absolute differences between two nodes last opinion about each other
            sum_differences += abs(int64(opinions_node[opinions_node.length - 1]) - int64(opinions_neighbour[opinions_neighbour.length - 1])) * MULTIPLIER;
            n_confirmed_neighbours++;
        }

        // return the average of all average differences between a node and all its neighbours
        return sum_differences > 0 && n_confirmed_neighbours > 0 ? sum_differences / n_confirmed_neighbours : 0;
    }

    function get_reputations(string[] memory neighbours) public view returns (Stats_Dict[] memory){

        // verify that msg.sender is registered before requesting reputations
        require(accounts[msg.sender].registered, "msg.sender did not register the neighbourhood.");
        uint index_requester = accounts[msg.sender].index;

        // initialize list of Stats_Dicts to return to the requester
        Stats_Dict[] memory reputations = new Stats_Dict[](neighbours.length);

        // initialize variable for summing up reputations for computing average later on
        uint64 sum_reputations = 0;
        uint64 valid_reputations = 0;

        // initialize the variables for computing the average deviation between each pair of nodes
        uint64 sum_opinion_deviations;

        // iterate over the list of node names, sent from the requester
        for (uint64 j=0; j<neighbours.length; j++){

            // keep record of sum and number of non-zero opinions about each neighbor for computing avg later on
            uint64 n_opinions;
            uint64 sum_opinions;

            // assign neighbours name to variable for simplified access
            string memory name_target = neighbours[j];

            // check if node to request the reputation from is known to the system
            // otherwise exclude the target node in the response
            if (names[name_target].in_adj == false){
                continue;
            }

            // get adj_matrix index of target node
            uint index_target = names[name_target].index;

            // create temporary list for retrieving all nodes opinion about the current target node
            uint64[] memory opinions = new uint64[](nodes.length);

            // iterate over all nodes in the adjacency matrix to retrieve the average opinion about a target node
            for (uint64 i = 0; i < nodes.length; i++) {

                // ignore an edge if not both neighbours did confirm the edge
                if (confirmed_neighbours(i, index_target) == false){
                    continue;
                }

                // load all retrieved opinions from storage into memory
                uint64[] memory participant_history = adj_matrix[i][index_target].opinions;

                // skip averaging the opinion history if there are none
                if (participant_history.length == 0) {continue;}

                // only include opinion values of the requested round
                uint64 round_opinion = participant_history[participant_history.length-1];

                // scale up sum to reduce integer division error
                round_opinion *= MULTIPLIER;

                // count the included opinions for computing the average later on
                opinions[i] = round_opinion;
                n_opinions++;
                sum_opinions += opinions[i];
            }

            // average all final opinions of all neighbouring nodes about a target node
            // after having averaged the individual nodes opinion about a target node
            uint64 final_opinion = n_opinions > 0 && sum_opinions > 0 ? uint64(sum_opinions / n_opinions) : 0;

            // add detailed reputation object to final list for poisoning detection
            if (n_opinions > 0){

                // add full stats_dict object to list which will be extended in next steps
                reputations[j] = Stats_Dict(
                    name_target,
                    final_opinion,
                    final_opinion,
                    0,
                    0,
                    final_opinion / (MULTIPLIER / 10),
                    0,
                    0,
                    0,
                    index_target,
                    avg_difference_to_neighbours(index_target),
                    0,
                    0
                );

                // add up to the variables for computing the average later on
                sum_reputations += final_opinion;
                valid_reputations++;

                // sum up values to compute the average later on
                sum_opinion_deviations += reputations[j].avg_difference_opinions;
            }
        }

        // if no valid reputations were collected, return all-zero reputations
        if (valid_reputations == 0){
            return reputations;
        }

        // sort list and compute median
        uint64 med = median(reputations, reputations.length - uint(valid_reputations));

        // compute average reputation
        uint64 avg = sum_reputations / valid_reputations;
        uint64 variance = 0;

        // compute variance of all NON-NULL reputations for aggregation round
        for (uint64 i = 0; i < reputations.length; i++) {
            if (reputations[i].reputation > 0){
                uint64 diff = reputations[i].reputation > avg ? reputations[i].reputation - avg : avg - reputations[i].reputation;
                variance += diff * diff;
            }
        }
        variance /= valid_reputations;

        // compute stddev from variance
        uint64 stddev = 0;
        if (variance > 0) {
            stddev = sqrt(variance);
        }

        // compute for every reputation the number of average deviation away from the median
        // use the median to account for the majority of honest and higher rated reputations
        for (uint64 i = 0; i < reputations.length; i++) {

            uint64 stddev_count = 0;
            if (stddev > 0 && reputations[i].reputation > 0){
                stddev_count = (abs(int64(med) - int64(reputations[i].reputation)) * MULTIPLIER) / stddev;
            }

            // weight the reputation about a target node by the latest opinion of the requesting node
            // this ensures that the weight of nodes, which are not trusted by the requesting node, are reduced
            uint index_target = reputations[i].index;
            uint length_opinions = adj_matrix[index_requester][index_target].opinions.length;
            if (length_opinions > 0){
                uint64 latest_opinion = adj_matrix[index_requester][index_target].opinions[length_opinions-1] * MULTIPLIER;
                reputations[i].final_reputation = (latest_opinion * reputations[i].final_reputation) / (100 * MULTIPLIER);
            }
            // the calling node's own reputation is squared to account for the reduction of the other nodes reputation
            else if (index_target == index_requester){
                reputations[i].final_reputation = (reputations[i].final_reputation**2) / (MULTIPLIER/1000);
            }
            reputations[i].weighted_reputation = reputations[i].final_reputation;


            // if stddev is larger than 5 percentage points, the nodes' reputations starts deviating unusually high
            // this value was evaluated by experiments using non-IID scenarios and can differ for scenarios using IID
            // if a node's reputation is lower than the median and deviates more than a stddev from the median,
            // it gets punished by dividing its reputation by multiplying the number of stddev differences with the stddev
            if (
                    stddev >= 5 * MULTIPLIER &&
                    stddev_count >= 1 * MULTIPLIER &&
                    reputations[i].final_reputation > 0
                ){

                // reduce the nodes influence to up (2x)**4 the deviation to the median
                // uint64 divisor =  MULTIPLIER * ((2 * stddev_count / MULTIPLIER)**2);
                // uint64 divisor = (2*stddev_count)**2 / MULTIPLIER;
                uint64 divisor = (2 * stddev_count)**2 / MULTIPLIER;

                // write the final punishment divisor to the dict to return
                reputations[i].divisor = divisor / (MULTIPLIER / 10);

                // reduce the node's reputation by the divisor
                reputations[i].final_reputation = ((reputations[i].final_reputation * MULTIPLIER) / divisor);

            } else {
                // if a node does not strongly deviate from the median,
                // its final reputation equals the initial reputation
                reputations[i].divisor = 10;
            }

            // retrieve the dictionary containing all the statistics for a target node
            Stats_Dict memory target = reputations[i];

            // scale down all statistical values
            // divide scaling factor by 10 to get floating point precision in Core of NEBULA logging
            target.reputation /= (MULTIPLIER / 10);
            target.stddev_count = stddev_count / (MULTIPLIER / 10);
            target.stddev = stddev / (MULTIPLIER / 10);
            target.median = med / (MULTIPLIER / 10);
            target.avg = avg / (MULTIPLIER / 10);
            target.avg_avg_difference_opinions = (sum_opinion_deviations / valid_reputations) / (MULTIPLIER / 10);
            target.avg_difference_opinions = target.avg_difference_opinions / (MULTIPLIER / 10);

            // the local opinion of two nodes about each others models is symmetric
            // if a node has a high average deviation to the neighbours' opinions
            // the node is suspected in trying to poison the reputation system
            // the reputation values are not representative and the node is excluded from aggregation
            // factors are for correcting the scaling
            if (
                target.avg_difference_opinions > 2 * target.avg_avg_difference_opinions &&
                target.avg_avg_difference_opinions >= 5 * 10
            ){
                target.final_reputation = 0;
                target.malicious_opinions = 1;
            }

            // store changed statistics back to dictionary to return
            reputations[i] = target;
        }


        return reputations;
    }

    function abs(int64 x) private pure returns (uint64) {
        x = x >= 0 ? x : -x;
        return uint64(x);
    }

    function sqrt(uint64 x) private pure returns (uint64 y) {
        uint64 z = (x + 1) / 2;
        y = x;
        while (z < y) {
            y = z;
            z = (x / z + z) / 2;
        }
    }

    function bubbleSort(Stats_Dict[] memory arr) private pure returns (Stats_Dict[] memory) {
        uint n = arr.length;
        for (uint64 i = 0; i < n - 1; i++) {
            for (uint64 j = 0; j < n - i - 1; j++) {
                if (arr[j].final_reputation < arr[j + 1].final_reputation) {
                    (arr[j], arr[j + 1]) = (arr[j + 1], arr[j]);
                }
            }
        }
        return arr;
    }

    function median(Stats_Dict[] memory array, uint n_zero_elements) private pure returns(uint64) {
        // sort array descending inplace and return median
        if (array.length == 0){ return 0;}
	    array = bubbleSort(array);
        uint new_length = array.length - n_zero_elements;
	    return
            array.length % 2 == 0 ?
            (array[new_length/2-1].reputation + array[new_length/2].reputation)/2 :
            array[new_length/2].reputation;
    }
}
