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

hashids = Hashids()
logger = logging.getLogger(__name__)
dirname = os.path.dirname(__file__)


def count_class_samples(scenario_name, dataloaders_files):
    """
    Counts the number of samples by class.

    Args:
        scenario_name (string): Name of the scenario.
        dataloaders_files (list): Files that contain the dataloaders.

    """

    result = {}
    dataloaders = []

    for file in dataloaders_files:
        with open(file, "rb") as f:
            dataloader = pickle.load(f)
            dataloaders.append(dataloader)

    for dataloader in dataloaders:
        for batch, labels in dataloader:
            for b, label in zip(batch, labels, strict=False):
                l = hashids.encode(label.item())
                if l in result:
                    result[l] += 1
                else:
                    result[l] = 1

    name_file = f"{dirname}/files/{scenario_name}/count_class.json"
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

    name_file = f"{dirname}/files/{scenario_name}/entropy.json"
    if os.path.exists(name_file):
        with open(name_file) as f:
            client_entropy = json.load(f)

    client_id_hash = hashids.encode(client_id)

    for batch, labels in dataloader:
        for b, label in zip(batch, labels, strict=False):
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


def save_results_csv(
    scenario_name: str,
    id: int,
    bytes_sent: int,
    bytes_recv: int,
    accuracy: float,
    loss: float,
    finish: bool,
):
    outdir = f"{dirname}/files/{scenario_name}"
    filename = "data_results.csv"
    data_results_file = os.path.join(outdir, filename)
    if exists(data_results_file):
        df = pd.read_csv(data_results_file)
    else:
        # Crear un DataFrame con columnas especificadas
        df = pd.DataFrame(columns=["id", "bytes_sent", "bytes_recv", "accuracy", "loss", "finish"])

    try:
        if id not in df["id"].values:
            # Si no existe, agregar una nueva entrada con el ID del nodo
            df = pd.concat(
                [
                    df,
                    pd.DataFrame({
                        "id": id,
                        "bytes_sent": None,
                        "bytes_recv": None,
                        "accuracy": None,
                        "loss": None,
                        "finish": False,
                    }),
                ],
                ignore_index=True,
            )

            df.to_csv(data_results_file, encoding="utf-8", index=False)
        else:
            if bytes_sent is not None:
                df.loc[df["id"] == id, "bytes_sent"] = bytes_sent
            if bytes_recv is not None:
                df.loc[df["id"] == id, "bytes_recv"] = bytes_recv
            if accuracy is not None:
                df.loc[df["id"] == id, "accuracy"] = accuracy
            if loss is not None:
                df.loc[df["id"] == id, "loss"] = loss
            if finish:
                df.loc[df["id"] == id, "finish"] = True
            df.to_csv(data_results_file, encoding="utf-8", index=False)

    except Exception as e:
        logger.warning(e)
