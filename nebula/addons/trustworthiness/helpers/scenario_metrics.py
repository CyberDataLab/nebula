import io
import logging
import os
import statistics
from datetime import datetime

import pandas as pd
import torch
from codecarbon import EmissionsTracker

from nebula.addons.trustworthiness.helpers.csv_io import read_csv

logger = logging.getLogger(__name__)

DATETIME_FORMAT = "%d/%m/%Y %H:%M:%S"


def get_elapsed_time(start_time, end_time):
    # Return scenario duration in minutes from the timestamps stored by the workload.
    start_date = datetime.strptime(start_time, DATETIME_FORMAT)
    end_date = datetime.strptime(end_time, DATETIME_FORMAT)
    return (end_date - start_date).total_seconds() / 60


def _trustworthiness_dir(scenario_name):
    # All scenario metrics are stored under the scenario trustworthiness directory.
    return os.path.join(os.environ.get("NEBULA_LOGS_DIR"), scenario_name, "trustworthiness")


def _global_data_results_path(scenario_name):
    # CFL/global metrics are written in the shared data_results.csv file.
    return os.path.join(_trustworthiness_dir(scenario_name), "data_results.csv")


def _participant_data_results_path(scenario_name, participant_id):
    # DFL/SDFL participant metrics are written in participant-specific CSV files.
    return os.path.join(_trustworthiness_dir(scenario_name), f"data_results_{participant_id}.csv")


def _read_global_results(scenario_name):
    # Load the aggregate scenario metrics once and let callers pick the columns they need.
    return read_csv(_global_data_results_path(scenario_name))


def _read_participant_results(scenario_name, participant_id):
    # Load local metrics for one participant.
    return read_csv(_participant_data_results_path(scenario_name, participant_id))


def _find_participant_row(data, participant_id, source_name):
    # Match both string and integer IDs because CSV typing can vary between runs.
    row = data[data["id"] == participant_id]
    if row.empty:
        row = _find_participant_row_by_int_id(data, participant_id)

    if row.empty:
        raise ValueError(f"Participant {participant_id} not found in {source_name}")

    return row.iloc[0]


def _find_participant_row_by_int_id(data, participant_id):
    # Retry numeric participant IDs when pandas read the id column as integers.
    try:
        return data[data["id"] == int(participant_id)]
    except (TypeError, ValueError):
        return data.iloc[0:0]


def _client_count(data):
    # Global CSVs include the server row, so client averages exclude one row.
    return len(_client_rows(data))


def _client_rows(data):
    # CFL writes client reports first and appends the server row last.
    return data.iloc[:-1] if len(data) > 1 else data


def _mean_client_column(data, column_name):
    # Average a global metric across clients while keeping the historical server-row exclusion.
    clients = _client_rows(data)
    return clients[column_name].sum() / max(1, len(clients))


def get_bytes_model(model):
    # Serialize the model state_dict to measure the bytes that would be transmitted.
    buffer = io.BytesIO()
    torch.save(model.state_dict(), buffer)
    return buffer.tell()


def get_bytes_sent_recv(scenario_name):
    # Return total and average upload/download bytes from aggregate scenario results.
    data = _read_global_results(scenario_name)
    number_files = len(data)

    total_upload_bytes = int(data["bytes_sent"].sum())
    total_download_bytes = int(data["bytes_recv"].sum())

    avg_upload_bytes = total_upload_bytes / number_files
    avg_download_bytes = total_download_bytes / number_files

    return total_upload_bytes, total_download_bytes, avg_upload_bytes, avg_download_bytes


def get_avg_loss_accuracy(scenario_name):
    # Return client-average test loss, accuracy, accuracy std, macro F1 and train accuracy.
    data = _read_global_results(scenario_name)
    clients = _client_rows(data)

    avg_loss = _mean_client_column(data, "loss")
    avg_accuracy = _mean_client_column(data, "accuracy")
    std_accuracy = statistics.stdev(clients["accuracy"]) if len(clients) > 1 else 0.0
    avg_macro_f1 = _mean_client_column(data, "macro_f1")
    avg_train_accuracy = _mean_client_column(data, "train_accuracy")

    return avg_loss, avg_accuracy, std_accuracy, avg_macro_f1, avg_train_accuracy


def get_underfitting_score(scenario_name, participant_id):
    # CFL underfitting uses the average validation accuracy across client rows.
    data = _read_global_results(scenario_name)
    return _mean_client_column(data, "val_accuracy")


def get_participant_loss_accuracy(scenario_name, participant_id):
    # Read one participant's final CFL loss and accuracy from the aggregate CSV.
    data_file = _global_data_results_path(scenario_name)
    row = _find_participant_row(read_csv(data_file), participant_id, data_file)
    return float(row["loss"]), float(row["accuracy"])


def get_underfitting_score_local(scenario_name, participant_id):
    # DFL/SDFL underfitting uses the participant-local validation accuracy.
    data = _read_participant_results(scenario_name, participant_id)
    return float(data["val_accuracy"].iloc[0])


def get_dp_local(scenario_name, participant_id):
    # Return DP settings stored by a single DFL/SDFL participant.
    data = _read_participant_results(scenario_name, participant_id)
    return data["dp_enabled"].iloc[0], float(data["dp_epsilon"].iloc[0])


def get_dp_global(scenario_name):
    # Return CFL DP settings, averaging epsilon across client rows when DP is enabled.
    data = _read_global_results(scenario_name)
    clients = _client_rows(data)

    if clients["dp_enabled"].iloc[0] == False:
        return False, 0.0

    return True, _mean_client_column(data, "dp_epsilon")


def get_avg_class_imbalance_model_size(scenario_name):
    # Return average class imbalance and model size across client rows.
    data = _read_global_results(scenario_name)
    clients = _client_rows(data)
    number_files = max(1, len(clients))

    avg_class_imbalance = clients["class_imbalance"].sum() / number_files
    avg_model_size = clients["model_size"].sum() / number_files

    return avg_class_imbalance, avg_model_size


def get_entropy_list(scenario_name):
    # Return client entropy values so callers can normalize the distribution.
    data = _read_global_results(scenario_name)
    return _client_rows(data)["local_entropy"].tolist()


def stop_emissions_tracking_and_save(
    tracker: EmissionsTracker,
    outdir: str,
    emissions_file: str,
    role: str,
    workload: str,
    sample_size: int = 0,
    participant_idx=None,
):
    # Stop CodeCarbon tracking and append the final emissions row to emissions.csv.
    tracker.stop()

    emissions_path = os.path.join(outdir, emissions_file)
    df = _read_or_create_emissions_dataframe(emissions_path)

    try:
        row = _build_emissions_row(tracker, role, workload, sample_size, participant_idx)
        df = pd.concat([df, pd.DataFrame(row)], ignore_index=True)
        df.to_csv(emissions_path, encoding="utf-8", index=False)
    except Exception as e:
        logger.warning(e)


def _read_or_create_emissions_dataframe(emissions_path):
    # Reuse the existing file when present, otherwise create the expected columns.
    if os.path.exists(emissions_path):
        return pd.read_csv(emissions_path)

    return pd.DataFrame(
        columns=[
            "id",
            "role",
            "energy_grid",
            "emissions",
            "workload",
            "CPU_model",
            "GPU_model",
        ]
    )


def _build_emissions_row(tracker, role, workload, sample_size, participant_idx):
    # Convert CodeCarbon's final data object into the CSV row persisted by trustworthiness.
    emissions_data = tracker.final_emissions_data
    energy_grid = (emissions_data.emissions / emissions_data.energy_consumed) * 1000

    return {
        "id": participant_idx,
        "role": role,
        "energy_grid": [energy_grid],
        "emissions": [emissions_data.emissions],
        "workload": workload,
        "CPU_model": emissions_data.cpu_model if emissions_data.cpu_model else "None",
        "GPU_model": emissions_data.gpu_model if emissions_data.gpu_model else "None",
        "CPU_used": bool(emissions_data.cpu_energy),
        "GPU_used": bool(emissions_data.gpu_energy),
        "energy_consumed": emissions_data.energy_consumed,
        "sample_size": sample_size,
    }


def comm_efficiency(bytes_up: int, bytes_down: int, test_acc_avg: float, eps: float = 1e-12) -> float:
    # Communication efficiency is total transferred bytes divided by final accuracy.
    total_bytes = float(bytes_up) + float(bytes_down)
    accuracy = max(float(test_acc_avg), eps)
    return total_bytes / accuracy
