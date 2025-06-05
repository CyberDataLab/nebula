import json
import logging
import math
import os
import pickle
from os.path import exists

import pandas as pd
from hashids import Hashids
from scipy.stats import entropy

from nebula.addons.trustworthiness import calculation
from collections import Counter

hashids = Hashids()
logger = logging.getLogger(__name__)
dirname = os.path.dirname(__file__)


def count_class_samples(scenario_name, dataloaders_files, class_counter: Counter = None):
    """
    Counts the number of samples by class.

    Args:
        scenario_name (string): Name of the scenario.
        dataloaders_files (list): Files that contain the dataloaders.

    """

    result = {}
    dataloaders = []
    
    if class_counter:
        result = {hashids.encode(int(class_id)): count for class_id, count in class_counter.items()}
    else:
        for file in dataloaders_files:
            with open(file, "rb") as f:
                dataloader = pickle.load(f)
                dataloaders.append(dataloader)

        for dataloader in dataloaders:
            for batch, labels in dataloader:
                for b, label in zip(batch, labels):
                    l = hashids.encode(label.item())
                    if l in result:
                        result[l] += 1
                    else:
                        result[l] = 1

    try:
        name_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", "count_class.json")
    except:
        name_file = os.path.join("nebula", "app", "logs", scenario_name, "trustworthiness", "count_class.json")
        
    with open(name_file, "w") as f:
        json.dump(result, f)


def get_entropy(client_id, scenario_name, dataloader):
    """
    Get the entropy of each client in the scenario.

    Args:
        client_id (int): The client id.
        scenario_name (string): Name of the scenario.
        dataloaders_files (list): Files that contain the dataloaders.

    """
    result = {}
    client_entropy = {}

    name_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", "entropy.json")
        
    if os.path.exists(name_file):
        with open(name_file, "r") as f:
            client_entropy = json.load(f)

    client_id_hash = hashids.encode(client_id)

    for batch, labels in dataloader:
        for b, label in zip(batch, labels):
            l = hashids.encode(label.item())
            if l in result:
                result[l] += 1
            else:
                result[l] = 1

    n = len(dataloader)
    entropy_value = entropy([x / n for x in result.values()], base=2)
    client_entropy[client_id_hash] = entropy_value
    with open(name_file, "w") as f:
        json.dump(client_entropy, f)


def read_csv(filename):
    """
    Read a CSV file.

    Args:
        filename (string): Name of the file.

    Returns:
        object: The CSV readed.

    """
    if exists(filename):
        return pd.read_csv(filename)


def check_field_filled(factsheet_dict, factsheet_path, value, empty=""):
    """
    Check if the field in the factsheet file is filled or not.

    Args:
        factsheet_dict (dict): The factshett dict.
        factsheet_path (list): The factsheet field to check.
        value (float): The value to add in the field.
        empty (string): If the value could not be appended, the empty string is returned.

    Returns:
        float: The value added in the factsheet or empty if the value could not be appened

    """
    if factsheet_dict[factsheet_path[0]][factsheet_path[1]]:
        return factsheet_dict[factsheet_path[0]][factsheet_path[1]]
    elif value != "" and value != "nan":
        if type(value) != str and type(value) != list:
            if math.isnan(value):
                return 0
            else:
                return value
        else:
            return value
    else:
        return empty


def get_input_value(input_docs, inputs, operation):
    """
    Gets the input value from input document and apply the metric operation on the value.

    Args:
        inputs_docs (map): The input document map.
        inputs (list): All the inputs.
        operation (string): The metric operation.

    Returns:
        float: The metric value

    """

    input_value = None
    args = []
    for i in inputs:
        source = i.get("source", "")
        field = i.get("field_path", "")
        input_doc = input_docs.get(source, None)
        if input_doc is None:
            logger.warning(f"{source} is null")
        else:
            input = get_value_from_path(input_doc, field)
            args.append(input)
    try:
        operationFn = getattr(calculation, operation)
        input_value = operationFn(*args)
    except TypeError:
        logger.warning(f"{operation} is not valid")

    return input_value


def get_value_from_path(input_doc, path):
    """
    Gets the input value from input document by path.

    Args:
        inputs_doc (map): The input document map.
        path (string): The field name of the input value of interest.

    Returns:
        float: The input value from the input document

    """

    d = input_doc
    for nested_key in path.split("/"):
        temp = d.get(nested_key)
        if isinstance(temp, dict):
            d = d.get(nested_key)
        else:
            return temp
    return None


def write_results_json(out_file, dict):
    """
    Writes the result to JSON.

    Args:
        out_file (string): The output file.
        dict (dict): The object to be witten into JSON.

    Returns:
        float: The input value from the input document

    """

    with open(out_file, "a") as f:
        json.dump(dict, f, indent=4)


def save_results_csv(scenario_name: str, id: int, bytes_sent: int, bytes_recv: int, accuracy: float, loss: float):
    try:
        data_results_file = os.path.join(os.environ.get('NEBULA_LOGS_DIR'), scenario_name, "trustworthiness", "data_results.csv")
    except:
        data_results_file = os.path.join("nebula", "app", "logs", scenario_name, "trustworthiness", "data_results.csv")
        
    if exists(data_results_file):
        df = pd.read_csv(data_results_file)
    else:
        df = pd.DataFrame(columns=["id", "bytes_sent", "bytes_recv", "accuracy", "loss"])
        
    try:
        # Add new entry to DataFrame
        new_data = pd.DataFrame({'id': [id], 'bytes_sent': [bytes_sent],
                                    'bytes_recv': [bytes_recv], 'accuracy': [accuracy],
                                    'loss': [loss]})
        df = pd.concat([df, new_data], ignore_index=True)

        df.to_csv(data_results_file, encoding='utf-8', index=False)

    except Exception as e:
        logger.warning(e)
