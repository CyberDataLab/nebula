import csv
import json
import logging
import os

import pandas as pd

logger = logging.getLogger(__name__)

# CSV schemas used by trustworthiness outputs. Keeping column order centralized
# avoids subtle differences between append writes and full report exports.
DATA_RESULTS_COLUMNS = [
    "id",
    "bytes_sent",
    "bytes_recv",
    "accuracy",
    "loss",
    "val_accuracy",
    "macro_f1",
    "train_accuracy",
    "dp_enabled",
    "dp_epsilon",
]

CFL_DATA_RESULTS_COLUMNS = [
    "id",
    "bytes_sent",
    "bytes_recv",
    "accuracy",
    "loss",
    "class_imbalance",
    "model_size",
    "local_entropy",
    "val_accuracy",
    "macro_f1",
    "train_accuracy",
    "dp_enabled",
    "dp_epsilon",
]

EMISSIONS_COLUMNS = [
    "id",
    "role",
    "energy_grid",
    "emissions",
    "workload",
    "CPU_model",
    "GPU_model",
    "CPU_used",
    "GPU_used",
    "energy_consumed",
    "sample_size",
]


def _logs_dir():
    # Prefer the runtime logs directory; keep the historical app path as fallback.
    return os.environ.get("NEBULA_LOGS_DIR") or os.path.join("nebula", "app", "logs")


def _trustworthiness_dir(scenario_name: str) -> str:
    # Every scenario stores trustworthiness artifacts in this subdirectory.
    return os.path.join(_logs_dir(), scenario_name, "trustworthiness")


def _trustworthiness_path(scenario_name: str, filename: str) -> str:
    # Build a concrete artifact path for a scenario.
    return os.path.join(_trustworthiness_dir(scenario_name), filename)


def _ensure_parent_dir(file_path: str) -> None:
    # Ensure CSV/JSON writes work even when the trust folder was not created yet.
    directory = os.path.dirname(file_path)
    if directory:
        os.makedirs(directory, exist_ok=True)


def _read_first_csv_row(file_path: str) -> dict:
    # Per-participant summary CSVs are expected to contain one current row.
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    with open(file_path, "r", newline="") as csv_file:
        rows = list(csv.DictReader(csv_file))

    if not rows:
        raise ValueError(f"No rows found in {file_path}")

    return rows[0]


def _read_or_empty_dataframe(file_path: str, columns: list[str]) -> pd.DataFrame:
    # Append flows start from the existing CSV or from an empty schema.
    if os.path.exists(file_path):
        return pd.read_csv(file_path)

    return pd.DataFrame(columns=columns)


def _append_csv_row(file_path: str, columns: list[str], row: dict) -> None:
    # Preserve the declared schema and ignore any unexpected keys in row.
    _ensure_parent_dir(file_path)
    df = _read_or_empty_dataframe(file_path, columns)
    new_row = pd.DataFrame([{column: row.get(column) for column in columns}])
    pd.concat([df, new_row], ignore_index=True).to_csv(file_path, encoding="utf-8", index=False)


def _write_csv_rows(file_path: str, fieldnames: list[str], rows: list[dict]) -> None:
    # Aggregate reports replace the previous CSV content in one write.
    _ensure_parent_dir(file_path)
    with open(file_path, "w", newline="") as csv_file:
        writer = csv.DictWriter(csv_file, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def _to_bool(value) -> bool:
    # DictReader returns strings, while some tests/builders may pass booleans.
    return str(value).strip().lower() == "true"


def read_csv(filename):
    # Missing optional CSVs are represented as None for existing callers.
    if os.path.exists(filename):
        return pd.read_csv(filename)

    return None


def write_results_json(out_file, data):
    # Trust metric evaluation appends one result object per evaluation call.
    _ensure_parent_dir(out_file)
    with open(out_file, "a", encoding="utf-8") as file:
        json.dump(data, file, indent=4)


def load_data_results_participant(experiment_name: str, participant_id: int | str):
    # Load the DFL/SDFL participant training summary written by save_results_csv.
    row = _read_first_csv_row(
        _trustworthiness_path(experiment_name, f"data_results_{participant_id}.csv")
    )
    macro_f1 = row["macro_f1"] or 0.0
    train_accuracy = row["train_accuracy"] or 0.0

    return (
        int(float(row["bytes_sent"])),
        int(float(row["bytes_recv"])),
        float(row["accuracy"]),
        float(row["loss"]),
        float(row["val_accuracy"]),
        float(macro_f1),
        float(train_accuracy),
        _to_bool(row["dp_enabled"]),
        float(row["dp_epsilon"]),
    )


def load_emissions_participant(experiment_name: str, participant_id: int | str):
    # Load the DFL/SDFL participant CodeCarbon summary.
    row = _read_first_csv_row(
        _trustworthiness_path(experiment_name, f"emissions_{participant_id}.csv")
    )

    return (
        str(row["role"]),
        float(row["energy_grid"]),
        float(row["emissions"]),
        str(row["workload"]),
        str(row["CPU_model"]),
        str(row["GPU_model"]),
        _to_bool(row["CPU_used"]),
        _to_bool(row["GPU_used"]),
        float(row["energy_consumed"]),
        int(float(row["sample_size"])),
    )


def save_trustworthiness_reports_csv(
    reports: dict,
    experiment_name: str,
) -> None:
    # Server-side CFL flow exports one aggregate data CSV and one emissions CSV.
    sorted_reports = sorted(reports.values(), key=lambda report: int(report["node_id"]))

    data_rows = [
        {
            "id": report["node_id"],
            "bytes_sent": report["bytes_sent"],
            "bytes_recv": report["bytes_recv"],
            "accuracy": report["accuracy"],
            "loss": report["loss"],
            "class_imbalance": report["class_imbalance"],
            "model_size": report["model_size"],
            "local_entropy": report["local_entropy"],
            "val_accuracy": report["val_accuracy"],
            "macro_f1": report["macro_f1"],
            "train_accuracy": report["train_accuracy"],
            "dp_enabled": report["dp_enabled"],
            "dp_epsilon": report["dp_epsilon"],
        }
        for report in sorted_reports
    ]
    emissions_rows = [
        {
            "id": report["node_id"],
            "role": report["role"],
            "energy_grid": report["energy_grid"],
            "emissions": report["emissions"],
            "workload": report["workload"],
            "CPU_model": report["cpu_model"],
            "GPU_model": report["gpu_model"],
            "CPU_used": report["cpu_used"],
            "GPU_used": report["gpu_used"],
            "energy_consumed": report["energy_consumed"],
            "sample_size": report["sample_size"],
        }
        for report in sorted_reports
    ]

    data_results_path = _trustworthiness_path(experiment_name, "data_results.csv")
    emissions_path = _trustworthiness_path(experiment_name, "emissions.csv")

    _write_csv_rows(data_results_path, CFL_DATA_RESULTS_COLUMNS, data_rows)
    _write_csv_rows(emissions_path, EMISSIONS_COLUMNS, emissions_rows)

    logger.info(
        "[TW SERVER] CSV files written correctly: %s, %s",
        data_results_path,
        emissions_path,
    )


def save_results_csv_cfl(
    scenario_name: str,
    id: int,
    bytes_sent: int,
    bytes_recv: int,
    accuracy: float,
    loss: float,
    class_imbalance: float,
    model_size: int,
    local_entropy: float,
    val_accuracy: float,
    macro_f1: float,
    train_accuracy: float,
    dp_enabled: bool,
    dp_epsilon: float,
):
    # Append one participant to the centralized data-results CSV.
    _append_csv_row(
        _trustworthiness_path(scenario_name, "data_results.csv"),
        CFL_DATA_RESULTS_COLUMNS,
        {
            "id": id,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "accuracy": accuracy,
            "loss": loss,
            "class_imbalance": class_imbalance,
            "model_size": model_size,
            "local_entropy": local_entropy,
            "val_accuracy": val_accuracy,
            "macro_f1": macro_f1,
            "train_accuracy": train_accuracy,
            "dp_enabled": dp_enabled,
            "dp_epsilon": dp_epsilon,
        },
    )


def save_emissions_csv_cfl(
    scenario_name: str,
    id: int,
    role: str,
    energy_grid: float,
    emissions: float,
    workload: str,
    cpu_model: str,
    gpu_model: str,
    cpu_used: bool,
    gpu_used: bool,
    energy_consumed: float,
    sample_size: int,
):
    # Append one participant to the centralized emissions CSV.
    _append_csv_row(
        _trustworthiness_path(scenario_name, "emissions.csv"),
        EMISSIONS_COLUMNS,
        {
            "id": id,
            "role": role,
            "energy_grid": energy_grid,
            "emissions": emissions,
            "workload": workload,
            "CPU_model": cpu_model,
            "GPU_model": gpu_model,
            "CPU_used": cpu_used,
            "GPU_used": gpu_used,
            "energy_consumed": energy_consumed,
            "sample_size": sample_size,
        },
    )


def save_results_csv(
    scenario_name: str,
    id: int,
    bytes_sent: int,
    bytes_recv: int,
    accuracy: float,
    loss: float,
    val_accuracy: float,
    macro_f1: float,
    train_accuracy: float,
    dp_enabled: bool,
    dp_epsilon: float,
):
    # Local DFL/SDFL nodes persist their own data-results CSV before exchange.
    _append_csv_row(
        _trustworthiness_path(scenario_name, f"data_results_{id}.csv"),
        DATA_RESULTS_COLUMNS,
        {
            "id": id,
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "accuracy": accuracy,
            "loss": loss,
            "val_accuracy": val_accuracy,
            "macro_f1": macro_f1,
            "train_accuracy": train_accuracy,
            "dp_enabled": dp_enabled,
            "dp_epsilon": dp_epsilon,
        },
    )
