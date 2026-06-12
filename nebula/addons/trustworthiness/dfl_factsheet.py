import logging
import os
import pandas as pd

from nebula.addons.trustworthiness.helpers.csv_io import (
    load_data_results_participant,
    load_emissions_participant,
)
from nebula.addons.trustworthiness.helpers.data_distribution import (
    get_all_data_entropy,
    get_local_class_imbalance_score,
    get_local_normalized_entropy,
)
from nebula.addons.trustworthiness.helpers.privacy import (
    get_global_privacy_risk_dfl,
)
from nebula.addons.trustworthiness.helpers.scenario_metrics import (
    get_bytes_model,
    get_dp_local,
    get_elapsed_time,
    get_underfitting_score_local,
)
from nebula.addons.trustworthiness.factsheet_common import (
    get_factsheet_path,
    get_factsheet_template_name,
    get_trustworthiness_dir,
    load_or_create_factsheet,
    populate_common_pre_train_sections,
    populate_participation,
    populate_reliability,
    populate_reputation,
    set_dp_configuration,
    write_factsheet,
)
from nebula.addons.trustworthiness.factsheet_populators import populate_profile_metrics

logger = logging.getLogger(__name__)

class DflFactsheet:
    def __init__(self):
        # Manage participant-specific DFL/SDFL factsheets.
        self.factsheet_template_file_nm = "factsheet_template_dfl.json"

    def populate_factsheet_dfl(
        self,
        scenario_name,
        participant_idx,
        data,
        start_time,
        end_time,
        model,
        train_loader,
        test_loader,
        reputation_summary=None,
        participation_summary=None,
        reliability_summary=None,
    ):

        # Resolve participant-specific output and data-type-aware template.
        self.factsheet_file_nm = f"factsheet_participant_{participant_idx}.json"
        factsheet_template_file_nm = get_factsheet_template_name(
            data["federation"],
            model,
            self.factsheet_template_file_nm,
            dataset_name=data["dataset"],
        )

        factsheet_file = get_factsheet_path(scenario_name, self.factsheet_file_nm)

        factsheet_file, factsheet = load_or_create_factsheet(
            scenario_name,
            self.factsheet_file_nm,
            factsheet_template_file_nm,
        )

        logging.info("DFL FactSheet: Populating factsheet")

        populate_common_pre_train_sections(factsheet, data, model)

        # DP configuration is stored per participant in decentralized runs.
        dp_enabled, dp_epsilon = get_dp_local(scenario_name, participant_idx)
        set_dp_configuration(factsheet, dp_enabled, dp_epsilon)

        files_dir = get_trustworthiness_dir(scenario_name)

        # Refresh entropy.json so participant-local entropy can be read consistently.
        get_all_data_entropy(scenario_name)

        factsheet["data"]["entropy_local"] = get_local_normalized_entropy(scenario_name, participant_idx)

        # Use the final valid round metrics as participant test performance.
        df = load_round_metrics(scenario_name, participant_idx)
        acc = df["accuracy"].astype(float).to_numpy()
        loss = df["loss"].astype(float).to_numpy()

        final_acc = float(acc[-1])
        final_loss = float(loss[-1])

        factsheet["performance"]["test_loss"] = float(final_loss)
        factsheet["performance"]["test_acc"] = float(final_acc)

        # Load local communication and privacy values reported by the participant.
        bytes_sent, bytes_recv, _, _, _, macro_f1, train_accuracy, *_ = load_data_results_participant(scenario_name, participant_idx)
        factsheet["performance"]["test_macro_f1"] = macro_f1
        factsheet["performance"]["train_accuracy"] = train_accuracy

        factsheet["system"]["model_size"] = get_bytes_model(model)

        factsheet["system"]["upload_bytes"] = int(bytes_sent)
        factsheet["system"]["download_bytes"] = int(bytes_recv)

        populate_reliability(factsheet, reliability_summary)

        factsheet["system"]["time_minutes"] = get_elapsed_time(start_time, end_time)

        # Class imbalance can only be populated after local class-counts exist.
        count_class_file = os.path.join(files_dir, f"{participant_idx}_class_count.json")
        factsheet["fairness"]["class_imbalance"] = (
            get_local_class_imbalance_score(scenario_name, participant_idx)
            if os.path.exists(count_class_file)
            else factsheet["fairness"].get("class_imbalance", 0.0)
        )

        populate_participation(factsheet, participation_summary)

        # Local CodeCarbon output feeds participant sustainability fields.
        (
            role,
            carbon_intensity_local,
            emissions_training_local,
            workload,
            cpu_model,
            gpu_model,
            cpu_used,
            gpu_used,
            energy_consumed_local,
            sample_size,
        ) = load_emissions_participant(
            scenario_name,
            participant_idx,
        )

        factsheet["sustainability"]["carbon_intensity_local"] = carbon_intensity_local
        factsheet["sustainability"]["emissions_training_local"] = emissions_training_local
        factsheet["sustainability"]["energy_consumed_local"] = energy_consumed_local
        factsheet["participants"]["local_dataset_size"] = sample_size

        populate_reputation(factsheet, reputation_summary, include_neighbor_num=True)
        # DFL privacy risk depends on local DP settings and neighbor count.
        factsheet["privacy"]["privacy_risk"] = get_global_privacy_risk_dfl(
            dp_enabled,
            dp_epsilon,
            factsheet["participants"]["neighbor_num"],
        )

        # Communication emissions are estimated from local bytes and carbon intensity.
        factsheet["sustainability"]["emissions_communication_local"] = (
            (bytes_sent * 2.24e-10 * carbon_intensity_local)
            + (bytes_recv * 2.24e-10 * carbon_intensity_local)
        )

        # Populate model/profile metrics after final participant accuracy is known.
        factsheet["fairness"]["underfitting"] = get_underfitting_score_local(scenario_name, participant_idx)
        populate_profile_metrics(
            factsheet,
            data["federation"],
            model,
            train_loader,
            test_loader,
            factsheet["performance"]["test_acc"],
        )

        write_factsheet(factsheet_file, factsheet)


def load_round_metrics(scenario_name, participant_idx):
    # Load participant per-round metrics and keep only rows with loss/accuracy.
    files_dir = get_trustworthiness_dir(scenario_name)
    path = os.path.join(files_dir, f"round_metrics_participant_{participant_idx}.csv")
    df = pd.read_csv(path)

    if "round" in df.columns:
        df = df.sort_values("round")

    df = df.dropna(subset=["loss", "accuracy"])
    return df
