import json
import logging
import os
import glob
import shutil
from json import JSONDecodeError
import pickle
import numpy as np
import pandas as pd

# from nebula.core.models.cifar10.cnn import CIFAR10ModelCNN
from nebula.core.models.mnist.mlp import MNISTModelMLP
from nebula.core.models.mnist.cnn import MNISTModelCNN
from nebula.addons.trustworthiness.calculation import get_elapsed_time, get_bytes_models, get_bytes_sent_recv, get_avg_loss_accuracy, get_cv, get_clever_score, get_feature_importance_cv
from nebula.addons.trustworthiness.utils import count_all_class_samples, read_csv, check_field_filled, get_all_data_entropy
# from nebula.core.models.syscall.mlp import SyscallModelMLP

dirname = os.path.dirname(__file__)

class Factsheet:
    def __init__(self):
        """
        Manager class to populate the FactSheet
        """
        self.factsheet_file_nm = "factsheet.json"
        self.factsheet_template_file_nm = "factsheet_template.json"

    def populate_factsheet_pre_train(self, data, scenario_name):
        """
        Populates the factsheet with values before the training.

        Args:
            data (dict): Contains the data from the scenario.
            scenario_name (string): The name of the scenario.
        """

        factsheet_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", self.factsheet_file_nm)

        factsheet_template = os.path.join(dirname, "configs", self.factsheet_template_file_nm)

        if not os.path.exists(factsheet_file):
            shutil.copyfile(factsheet_template, factsheet_file)

        with open(factsheet_file, "r+") as f:
            factsheet = {}

            try:
                factsheet = json.load(f)

                if data is not None:
                    logging.info("FactSheet: Populating factsheet with pre training metrics")

                    federation = data["federation"]
                    n_nodes = int(data["n_nodes"])
                    dataset = data["dataset"]
                    algorithm = data["model"]
                    aggregation_algorithm = data["agg_algorithm"]
                    n_rounds = int(data["rounds"])
                    attack = data["attack_params"]["attacks"]
                    if attack != "No Attack":
                        poisoned_node_percent = int(data["attack_params"]["poisoned_node_percent"])
                        poisoned_sample_percent = int(data["attack_params"]["poisoned_sample_percent"])
                        poisoned_noise_percent = int(data["attack_params"]["poisoned_noise_percent"])
                    else:
                        poisoned_node_percent = 0
                        poisoned_sample_percent = 0
                        poisoned_noise_percent = 0
                    with_reputation = data["reputation"]["enabled"]
                    is_dynamic_topology = False # data["is_dynamic_topology"]
                    is_dynamic_aggregation = False # data["is_dynamic_aggregation"]
                    target_aggregation = False # data["target_aggregation"]

                    if attack != "No Attack" and with_reputation == True and is_dynamic_aggregation == True:
                        background = f"For the project setup, the most important aspects are the following: The federation architecture is {federation}, involving {n_nodes} clients, the dataset used is {dataset}, the learning algorithm is {algorithm}, the aggregation algorithm is {aggregation_algorithm} and the number of rounds is {n_rounds}. In addition, the type of attack used against the clients is {attack}, where the percentage of attacked nodes is {poisoned_node_percent}, the percentage of attacked samples of each node is {poisoned_sample_percent}, and the percent of poisoned noise is {poisoned_noise_percent}. A reputation-based defence with a dynamic aggregation based on the aggregation algorithm {target_aggregation} is used, and the trustworthiness of the project is desired."

                    elif attack != "No Attack" and with_reputation == True and is_dynamic_topology == True:
                        background = f"For the project setup, the most important aspects are the following: The federation architecture is {federation}, involving {n_nodes} clients, the dataset used is {dataset}, the learning algorithm is {algorithm}, the aggregation algorithm is {aggregation_algorithm} and the number of rounds is {n_rounds}. In addition, the type of attack used against the clients is {attack}, where the percentage of attacked nodes is {poisoned_node_percent}, the percentage of attacked samples of each node is {poisoned_sample_percent}, and the percent of poisoned noise is {poisoned_noise_percent}. A reputation-based defence with a dynamic topology is used, and the trustworthiness of the project is desired."

                    elif attack != "No Attack" and with_reputation == False:
                        background = f"For the project setup, the most important aspects are the following: The federation architecture is {federation}, involving {n_nodes} clients, the dataset used is {dataset}, the learning algorithm is {algorithm}, the aggregation algorithm is {aggregation_algorithm} and the number of rounds is {n_rounds}. In addition, the type of attack used against the clients is {attack}, where the percentage of attacked nodes is {poisoned_node_percent}, the percentage of attacked samples of each node is {poisoned_sample_percent}, and the percent of poisoned noise is {poisoned_noise_percent}. No defence mechanism is used, and the trustworthiness of the project is desired."

                    elif attack == "No Attack":
                        background = f"For the project setup, the most important aspects are the following: The federation architecture is {federation}, involving {n_nodes} clients, the dataset used is {dataset}, the learning algorithm is {algorithm}, the aggregation algorithm is {aggregation_algorithm} and the number of rounds is {n_rounds}. No attacks against clients are used, and the trustworthiness of the project is desired."

                    # Set project specifications
                    factsheet["project"]["overview"] = data["scenario_title"]
                    factsheet["project"]["purpose"] = data["scenario_description"]
                    factsheet["project"]["background"] = background

                    # Set data specifications
                    factsheet["data"]["provenance"] = data["dataset"]
                    factsheet["data"]["preprocessing"] = data["topology"]

                    # Set participants
                    factsheet["participants"]["client_num"] = data["n_nodes"] or ""
                    factsheet["participants"]["sample_client_rate"] = 1
                    factsheet["participants"]["client_selector"] = ""

                    # Set configuration
                    factsheet["configuration"]["aggregation_algorithm"] = data["agg_algorithm"] or ""
                    factsheet["configuration"]["training_model"] = data["model"] or ""
                    factsheet["configuration"]["personalization"] = False
                    factsheet["configuration"]["visualization"] = True
                    factsheet["configuration"]["total_round_num"] = n_rounds

                    if poisoned_noise_percent != 0:
                        factsheet["configuration"]["differential_privacy"] = True
                        factsheet["configuration"]["dp_epsilon"] = poisoned_noise_percent
                    else:
                        factsheet["configuration"]["differential_privacy"] = False
                        factsheet["configuration"]["dp_epsilon"] = ""

                    if dataset == "MNIST" and algorithm == "MLP":
                        model = MNISTModelMLP()
                    elif dataset == "MNIST" and algorithm == "CNN":
                        model = MNISTModelCNN()
                    # elif dataset == "Syscall" and algorithm == "MLP":
                    #     model = SyscallModelMLP()
                    # else:
                    #     model = CIFAR10ModelCNN()

                    factsheet["configuration"]["learning_rate"] = model.get_learning_rate()
                    factsheet["configuration"]["trainable_param_num"] = model.count_parameters()
                    factsheet["configuration"]["local_update_steps"] = 1

                    f.seek(0)
                    f.truncate()
                    json.dump(factsheet, f, indent=4)

            except JSONDecodeError as e:
                logging.warning(f"{factsheet_file} is invalid")
                logging.error(e)

    def populate_factsheet_post_train(self, scenario_name, start_time, end_time):
        """
        Populates the factsheet with values after the training.

        Args:
            scenario (object): The scenario object.
        """
        factsheet_file = os.path.join(f"{os.environ.get('NEBULA_LOGS_DIR')}{scenario_name}/trustworthiness/{self.factsheet_file_nm}")

        logging.info("FactSheet: Populating factsheet with post training metrics")

        with open(factsheet_file, "r+") as f:
            factsheet = {}
            try:
                factsheet = json.load(f)

                dataset = factsheet["data"]["provenance"]
                model = factsheet["configuration"]["training_model"]

                files_dir = f"{os.environ.get('NEBULA_LOGS_DIR')}/{scenario_name}/trustworthiness"

                models_files = glob.glob(os.path.join(files_dir, "*final_model*"))
                #dataloaders_files = glob.glob(os.path.join(files_dir, "*train_loader*"))
                test_dataloader_file = f"{files_dir}/participant_1_test_loader.pk"
                train_model_file = f"{files_dir}/participant_1_train_model.pk"
                emissions_file = os.path.join(files_dir, "emissions.csv")

                # # Entropy
                # i = 0
                # for file in dataloaders_files:
                #     with open(file, "rb") as file:
                #         dataloader = pickle.load(file)
                #     get_entropy(i, scenario_name, dataloader)
                #     i += 1
                
                get_all_data_entropy(scenario_name)

                with open(f"{files_dir}/entropy.json", "r") as file:
                    entropy_distribution = json.load(file)

                values = np.array(list(entropy_distribution.values()))

                normalized_values = (values - np.min(values)) / (np.max(values) - np.min(values))

                avg_entropy = np.mean(normalized_values)

                factsheet["data"]["avg_entropy"] = avg_entropy

                # Set performance data
                result_avg_loss_accuracy = get_avg_loss_accuracy(scenario_name)
                factsheet["performance"]["test_loss_avg"] = result_avg_loss_accuracy[0]
                factsheet["performance"]["test_acc_avg"] = result_avg_loss_accuracy[1]
                test_acc_cv = get_cv(std=result_avg_loss_accuracy[2], mean=result_avg_loss_accuracy[1])
                factsheet["fairness"]["test_acc_cv"] = 1 if test_acc_cv > 1 else test_acc_cv

                factsheet["system"]["avg_time_minutes"] = get_elapsed_time(start_time, end_time)
                factsheet["system"]["avg_model_size"] = get_bytes_models(models_files)

                result_bytes_sent_recv = get_bytes_sent_recv(scenario_name)
                factsheet["system"]["total_upload_bytes"] = result_bytes_sent_recv[0]
                factsheet["system"]["total_download_bytes"] = result_bytes_sent_recv[1]
                factsheet["system"]["avg_upload_bytes"] = result_bytes_sent_recv[2]
                factsheet["system"]["avg_download_bytes"] = result_bytes_sent_recv[3]

                factsheet["fairness"]["selection_cv"] = 1

                count_all_class_samples(scenario_name)
                
                with open(f"{files_dir}/count_class.json", "r") as file:
                    class_distribution = json.load(file)

                class_samples_sizes = [x for x in class_distribution.values()]
                class_imbalance = get_cv(list=class_samples_sizes)
                factsheet["fairness"]["class_imbalance"] = 1 if class_imbalance > 1 else class_imbalance

                with open(train_model_file, "rb") as file:
                    lightning_model = pickle.load(file)

                if dataset == "MNIST" and model == "MLP":
                    model = MNISTModelMLP()
                elif dataset == "MNIST" and model == "CNN":
                    model = MNISTModelCNN()
                # elif dataset == "Syscall" and model == "MLP":
                #     model = SyscallModelMLP()
                # else:
                #     model = CIFAR10ModelCNN()
                
                model.load_state_dict(lightning_model.state_dict())

                with open(test_dataloader_file, "rb") as file:
                    test_dataloader = pickle.load(file)

                test_sample = next(iter(test_dataloader))

                lr = factsheet["configuration"]["learning_rate"]
                value_clever = get_clever_score(model, test_sample, 10, lr)

                factsheet["performance"]["test_clever"] = 1 if value_clever > 1 else value_clever

                feature_importance = get_feature_importance_cv(model, test_sample)

                factsheet["performance"]["test_feature_importance_cv"] = 1 if feature_importance > 1 else feature_importance

                # Set emissions metrics
                emissions = None if emissions_file is None else read_csv(emissions_file)
                if emissions is not None:
                    logging.info("FactSheet: Populating emissions")
                    cpu_spez_df = pd.read_csv(os.path.join(os.path.dirname(__file__), "benchmarks", "CPU_benchmarks_v4.csv"), header=0)
                    emissions["CPU_model"] = emissions["CPU_model"].astype(str).str.replace(r"\([^)]*\)", "", regex=True)
                    emissions["CPU_model"] = emissions["CPU_model"].astype(str).str.replace(r" CPU", "", regex=True)
                    emissions["GPU_model"] = emissions["GPU_model"].astype(str).str.replace(r"[0-9] x ", "", regex=True)
                    emissions = pd.merge(emissions, cpu_spez_df[["cpuName", "powerPerf"]], left_on="CPU_model", right_on="cpuName", how="left")
                    gpu_spez_df = pd.read_csv(os.path.join(os.path.dirname(__file__), "benchmarks", "GPU_benchmarks_v7.csv"), header=0)
                    emissions = pd.merge(emissions, gpu_spez_df[["gpuName", "powerPerformance"]], left_on="GPU_model", right_on="gpuName", how="left")

                    emissions.drop("cpuName", axis=1, inplace=True)
                    emissions.drop("gpuName", axis=1, inplace=True)
                    emissions["powerPerf"] = emissions["powerPerf"].astype(float)
                    emissions["powerPerformance"] = emissions["powerPerformance"].astype(float)
                    client_emissions = emissions.loc[emissions["role"] == "trainer"]
                    client_avg_carbon_intensity = round(client_emissions["energy_grid"].mean(), 2)
                    factsheet["sustainability"]["avg_carbon_intensity_clients"] = check_field_filled(factsheet, ["sustainability", "avg_carbon_intensity_clients"], client_avg_carbon_intensity, "")
                    factsheet["sustainability"]["emissions_training"] = check_field_filled(factsheet, ["sustainability", "emissions_training"], client_emissions["emissions"].sum(), "")
                    factsheet["participants"]["avg_dataset_size"] = check_field_filled(factsheet, ["participants", "avg_dataset_size"], client_emissions["sample_size"].mean(), "")
                    GPU_powerperf = (client_emissions.loc[client_emissions["GPU_used"] == True])["powerPerformance"]
                    CPU_powerperf = (client_emissions.loc[client_emissions["CPU_used"] == True])["powerPerf"]
                    clients_power_performance = round(pd.concat([GPU_powerperf, CPU_powerperf]).mean(), 2)
                    factsheet["sustainability"]["avg_power_performance_clients"] = check_field_filled(factsheet, ["sustainability", "avg_power_performance_clients"], clients_power_performance, "")

                    server_emissions = emissions.loc[emissions["role"] == "server"]
                    server_avg_carbon_intensity = round(server_emissions["energy_grid"].mean(), 2)
                    factsheet["sustainability"]["avg_carbon_intensity_server"] = check_field_filled(factsheet, ["sustainability", "avg_carbon_intensity_server"], server_avg_carbon_intensity, "")
                    factsheet["sustainability"]["emissions_aggregation"] = check_field_filled(factsheet, ["sustainability", "emissions_aggregation"], server_emissions["emissions"].sum(), "")
                    GPU_powerperf = (server_emissions.loc[server_emissions["GPU_used"] == True])["powerPerformance"]
                    CPU_powerperf = (server_emissions.loc[server_emissions["CPU_used"] == True])["powerPerf"]
                    server_power_performance = round(pd.concat([GPU_powerperf, CPU_powerperf]).mean(), 2)
                    factsheet["sustainability"]["avg_power_performance_server"] = check_field_filled(factsheet, ["sustainability", "avg_power_performance_server"], server_power_performance, "")

                    factsheet["sustainability"]["emissions_communication_uplink"] = check_field_filled(factsheet, ["sustainability", "emissions_communication_uplink"], factsheet["system"]["total_upload_bytes"] * 2.24e-10 * factsheet["sustainability"]["avg_carbon_intensity_clients"], "")
                    factsheet["sustainability"]["emissions_communication_downlink"] = check_field_filled(factsheet, ["sustainability", "emissions_communication_downlink"], factsheet["system"]["total_download_bytes"] * 2.24e-10 * factsheet["sustainability"]["avg_carbon_intensity_server"], "")

                f.seek(0)
                f.truncate()
                json.dump(factsheet, f, indent=4)

            except JSONDecodeError as e:
                logging.info(f"{factsheet_file} is invalid")
                logging.error(e)