import logging
import asyncio
from nebula.addons.functions import print_msg_box
from nebula.core.nebulaevents import AggregationEvent, ExperimentFinishEvent, RoundStartEvent, TestMetricsEvent, ValidationMetricsEvent
from nebula.core.eventmanager import EventManager
from nebula.core.noderole import Role, ServerRoleBehavior
from abc import ABC, abstractmethod
from nebula.config.config import Config
from nebula.core.engine import Engine
from nebula.addons.trustworthiness.helpers.csv_io import (
    load_data_results_participant,
    load_emissions_participant,
    save_emissions_csv_cfl,
    save_results_csv,
    save_results_csv_cfl,
    save_trustworthiness_reports_csv,
)
from nebula.addons.trustworthiness.helpers.data_distribution import (
    get_class_imbalance_local,
    get_local_entropy,
    get_participation_variation_score,
    save_class_count_per_participant,
)
from nebula.addons.trustworthiness.helpers.scenario_metrics import (
    get_bytes_model,
    stop_emissions_tracking_and_save,
)
from nebula.addons.trustworthiness.helpers.trust_reports import (
    accumulate_weighted_trustscores,
    build_weighted_trustscores_report,
    create_local_trust_report_copy,
    load_trust_report_json_dumped,
    save_trust_report_json,
)
from codecarbon import EmissionsTracker
from nebula.addons.trustworthiness.per_round_metrics import PerRoundTrustMetrics
from datetime import datetime
from nebula.addons.trustworthiness.cfl_factsheet import CflFactsheet
from nebula.addons.trustworthiness.metric import TrustMetricManager
from nebula.addons.trustworthiness.dfl_factsheet import DflFactsheet
from nebula.addons.trustworthiness.graphics import Graphics
from nebula.addons.trustworthiness.weights import load_trust_weights
import json
import os
from nebula.core.network.communications import CommunicationsManager

"""                                                     ##############################
                                                        #       TRUST WORKLOADS      #
                                                        ##############################
"""

class TrustWorkloadException(Exception):
    pass

class TrustWorkload(ABC):
    @abstractmethod
    async def init(self, experiment_name):
        # Initialize workload resources and event subscriptions.
        raise NotImplementedError

    @abstractmethod
    def get_workload(self) -> str:
        # Return the workload label persisted in trustworthiness outputs.
        raise NotImplementedError

    @abstractmethod
    def get_sample_size(self) -> float:
        # Return the local sample size used by the workload.
        raise NotImplementedError

    @abstractmethod
    def get_metrics(self) -> tuple[float, float, float]:
        # Return the latest test loss, accuracy and macro F1.
        raise NotImplementedError

    @abstractmethod
    async def finish_experiment_role_pre_actions(self):
        # Run role-specific work before final metrics are persisted.
        raise NotImplementedError

    @abstractmethod
    async def finish_experiment_role_post_actions(self, trust_config, experiment_name):
        # Run role-specific work after final metrics are persisted.
        raise NotImplementedError

class BaseTrustWorkload(TrustWorkload):
    def __init__(self, engine: Engine, idx, trust_files_route, workload: str, role_label: str, sample_size=None, start_time=None):
        # Store shared workload state used by trainers and servers.
        self._engine: Engine = engine
        self._workload = workload
        self._idx = idx
        self._trust_files_route = trust_files_route
        self._sample_size = sample_size
        self._current_loss = None
        self._current_accuracy = None
        self._current_macro_f1 = None
        self._current_val_loss = None
        self._current_val_accuracy = None
        self._current_train_accuracy = None
        self._experiment_name = ""
        self._per_round = None
        self._role_label = role_label
        self._start_time = start_time or datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self._end_time = None
        self._round_participation_counts = {}
        self._dropout_expected_total = 0
        self._dropout_missing_total = 0
        self._aggregation_rounds_total = 0
        self._timed_out_rounds_total = 0

    async def init(self, experiment_name):
        # Subscribe to the events needed to build final trust summaries.
        self._experiment_name = experiment_name
        await EventManager.get_instance().subscribe_node_event(AggregationEvent, self._process_aggregation_event)
        await EventManager.get_instance().subscribe_node_event(RoundStartEvent, self._process_round_start_event)
        await EventManager.get_instance().subscribe_addonevent(TestMetricsEvent, self._process_test_metrics_event)
        await EventManager.get_instance().subscribe_addonevent(ValidationMetricsEvent, self._process_validation_metrics_event)

        self._per_round = PerRoundTrustMetrics(
            experiment_name=experiment_name,
            participant_idx=self._idx,
            trust_dir=self._trust_files_route,
            role_label=self._role_label,
            enable_print=True,
            enable_csv=True,
        )
        await self._per_round.setup(self._engine)

    def get_workload(self):
        # Return the workload name associated with this node role.
        return self._workload

    def get_sample_size(self):
        # Return the sample size captured by the role pre-actions.
        return self._sample_size

    def get_metrics(self):
        # Return the latest test metrics observed through events.
        return (self._current_loss, self._current_accuracy, self._current_macro_f1)

    def get_validation_metrics(self):
        # Return the latest validation metrics and train accuracy observed through events.
        return (self._current_val_loss, self._current_val_accuracy, self._current_train_accuracy)

    def _is_reputation_enabled(self) -> bool:
        # Read the reputation toggle from the participant defense config.
        defense_args = self._engine.config.participant.get("defense_args", {})
        reputation_config = defense_args.get("reputation", {})
        return bool(reputation_config.get("enabled", False))

    def _get_reputation_system(self):
        # Return the reputation system attached to the engine, when present.
        return getattr(self._engine, "_reputation", None)

    def _get_reputation_trust_summary(self) -> dict:
        # Build the reputation fields added to the trust factsheet.
        summary = {
            "reputation_enabled": self._is_reputation_enabled(),
            "avg_neighbor_reputation": 0.0,
        }
        if hasattr(self, "_expected_trustscores_sources"):
            summary["neighbor_num"] = len(self._expected_trustscores_sources)

        if not summary["reputation_enabled"]:
            return summary

        reputation_system = self._get_reputation_system()
        reputation_values = []
        if reputation_system is not None:
            for addr, data in reputation_system.reputation.items():
                if addr == self._engine.addr:
                    continue

                reputation_value = data.get("reputation")
                if reputation_value is not None:
                    reputation_values.append(float(reputation_value))

        if reputation_values:
            summary["avg_neighbor_reputation"] = sum(reputation_values) / len(reputation_values)
        else:
            reputation_config = self._engine.config.participant.get("defense_args", {}).get("reputation", {})
            summary["avg_neighbor_reputation"] = float(reputation_config.get("initial_reputation", 0.0) or 0.0)

        return summary

    def _get_participation_trust_summary(self) -> dict:
        # Build the participation variability fields added to the trust factsheet.
        total_clients = int(self._engine.config.participant["scenario_args"]["n_nodes"]) - 1
        counts = list(self._round_participation_counts.values())

        if len(counts) < total_clients:
            counts.extend([0] * (total_clients - len(counts)))

        return {
            "selection_cv": get_participation_variation_score(counts),
        }

    def _get_system_reliability_summary(self) -> dict:
        # Build dropout and timeout rates from aggregation events.
        dropout_rate = 0.0
        if self._dropout_expected_total > 0:
            dropout_rate = self._dropout_missing_total / self._dropout_expected_total

        timeout_rate = 0.0
        if self._aggregation_rounds_total > 0:
            timeout_rate = self._timed_out_rounds_total / self._aggregation_rounds_total

        return {
            "dropout_rate": float(dropout_rate),
            "timeout_rate": float(timeout_rate),
        }

    async def _process_round_start_event(self, rse: RoundStartEvent):
        # Track how often each peer is expected to participate.
        _, _, expected_nodes = await rse.get_event_data()
        for node_addr in expected_nodes:
            self._round_participation_counts[node_addr] = self._round_participation_counts.get(node_addr, 0) + 1

    async def _process_aggregation_event(self, age: AggregationEvent):
        # Track missing peers and timed-out aggregation rounds.
        _, expected_nodes, missing_nodes = await age.get_event_data()
        self_addr = self._engine.addr

        expected_without_self = {node for node in expected_nodes if node != self_addr}
        missing_without_self = {node for node in missing_nodes if node != self_addr}

        self._aggregation_rounds_total += 1
        self._dropout_expected_total += len(expected_without_self)
        self._dropout_missing_total += len(missing_without_self)
        if missing_without_self:
            self._timed_out_rounds_total += 1

    async def _process_test_metrics_event(self, tme: TestMetricsEvent):
        # Cache final test metrics and forward them to per-round trust metrics.
        cur_loss, cur_acc, cur_macro_f1 = await tme.get_event_data()
        if cur_loss is not None and cur_acc is not None:
            self._current_loss, self._current_accuracy = cur_loss, cur_acc
            self._current_macro_f1 = cur_macro_f1

            if self._per_round is not None:
                await self._per_round.on_test_metrics(self._engine, float(cur_loss), float(cur_acc))

    async def _process_validation_metrics_event(self, vme: ValidationMetricsEvent):
        # Cache final validation metrics for final trustworthiness outputs.
        cur_loss, cur_acc, train_acc = await vme.get_event_data()
        if cur_loss is not None and cur_acc is not None:
            self._current_val_loss, self._current_val_accuracy = cur_loss, cur_acc
            self._current_train_accuracy = train_acc


class TrustWorkloadTrainer(BaseTrustWorkload):
    TRUSTSCORES_WAIT_TIMEOUT_SECONDS = 20
    TRUSTSCORES_FORWARDING_GRACE_SECONDS = 1.0
    TRUSTSCORES_FORWARDING_GRACE_MARGIN_SECONDS = 1.0

    def __init__(self, engine, idx, trust_files_route):
        # Initialize trainer-side state for CFL reports and DFL/SDFL trustscores.
        super().__init__(engine, idx, trust_files_route, workload="training", role_label="TRAINER")
        self._expected_trustscores_sources = set()
        self._expected_trustscores_reports = int(self._engine.config.participant["scenario_args"]["n_nodes"]) - 1
        self._received_trustscores_node_ids = set()
        self._trustscores_wait_event = None
        self._trustscores_score_accumulator = {}
        self._trustscores_weight_accumulator = {}
        self._trustscores_template_report = None
        self._trustscores_local_copy_path = None
        self._trustscores_local_report_initialized = False

    async def init(self, experiment_name):
        # Reset exchange state before subscribing to shared workload events.
        self._reset_trustscores_exchange_state()
        self._trustscores_wait_event = asyncio.Event()
        await super().init(experiment_name)

    async def finish_experiment_role_pre_actions(self):
        # Capture the training sample size before final trust outputs are written.
        self._engine.trainer.datamodule.setup(stage="fit")
        train_loader = self._engine.trainer.datamodule.train_dataloader()
        self._sample_size = len(train_loader)

    async def finish_experiment_role_post_actions(self, trust_config, experiment_name):
        # Finish with the report flow required by the selected federation type.
        federation = trust_config.get("federation")

        if self._uses_trustscores_exchange(federation):
            await self._finish_trustscores_exchange(federation, trust_config, experiment_name)
            return

        await self._send_cfl_trustworthiness_report(experiment_name)

    def _uses_trustscores_exchange(self, federation: str | None) -> bool:
        # DFL and SDFL share trust reports directly between participants.
        return federation in {"DFL", "SDFL"}

    async def _send_cfl_trustworthiness_report(self, experiment_name: str):
        # Send the participant trustworthiness report to the CFL server.
        cm = CommunicationsManager.get_instance()
        server_addr = str(self._engine.config.participant["network_args"]["neighbors"]).strip()
        report = self._build_cfl_trustworthiness_report(experiment_name)

        message = cm.create_message(
            "trustworthiness",
            action="report",
            node_id=str(self._idx),
            **report,
        )

        self._log_cfl_trustworthiness_report(server_addr, report)

        await cm.send_message(
            server_addr,
            message,
            message_type="trustworthiness",
            allow_after_learning_finished=True,
        )

    def _build_cfl_trustworthiness_report(self, experiment_name: str) -> dict:
        # Load local metrics and shape them as a trustworthiness message payload.
        bytes_sent, bytes_recv, accuracy, loss, val_accuracy, macro_f1, train_accuracy, dp_enabled, dp_epsilon = load_data_results_participant(
            experiment_name,
            self._idx,
        )
        role, energy_grid, emissions, workload, cpu_model, gpu_model, cpu_used, gpu_used, energy_consumed, sample_size = load_emissions_participant(
            experiment_name,
            self._idx,
        )

        return {
            "bytes_sent": bytes_sent,
            "bytes_recv": bytes_recv,
            "accuracy": accuracy,
            "loss": loss,
            "role": role,
            "energy_grid": energy_grid,
            "emissions": emissions,
            "workload": workload,
            "cpu_model": cpu_model,
            "gpu_model": gpu_model,
            "cpu_used": cpu_used,
            "gpu_used": gpu_used,
            "energy_consumed": energy_consumed,
            "sample_size": sample_size,
            "class_imbalance": get_class_imbalance_local(self._idx, experiment_name),
            "model_size": get_bytes_model(self._engine.trainer.model),
            "local_entropy": get_local_entropy(self._idx, experiment_name),
            "val_accuracy": val_accuracy,
            "macro_f1": macro_f1,
            "train_accuracy": train_accuracy,
            "dp_enabled": dp_enabled,
            "dp_epsilon": dp_epsilon,
        }

    def _log_cfl_trustworthiness_report(self, server_addr: str, report: dict):
        # Log the CFL report with the same fields sent over the network.
        logging.info(
            "[TW SEND] dest=%s node_id=%s bytes_sent=%s bytes_recv=%s "
            "accuracy=%s loss=%s role=%s energy_grid=%s emissions=%s workload=%s "
            "cpu_model=%s gpu_model=%s cpu_used=%s gpu_used=%s energy_consumed=%s sample_size=%s class_imbalance=%s model_size=%s local_entropy=%s val_accuracy=%s dp_enabled=%s dp_epsilon=%s macro_f1=%s train_accuracy=%s",
            server_addr,
            str(self._idx),
            report["bytes_sent"],
            report["bytes_recv"],
            report["accuracy"],
            report["loss"],
            report["role"],
            report["energy_grid"],
            report["emissions"],
            report["workload"],
            report["cpu_model"],
            report["gpu_model"],
            report["cpu_used"],
            report["gpu_used"],
            report["energy_consumed"],
            report["sample_size"],
            report["class_imbalance"],
            report["model_size"],
            report["local_entropy"],
            report["val_accuracy"],
            report["dp_enabled"],
            report["dp_epsilon"],
            report["macro_f1"],
            report["train_accuracy"],
        )

    async def _finish_trustscores_exchange(self, federation, trust_config, experiment_name):
        # Compute, share, wait for, and optionally aggregate DFL/SDFL trustscores.
        self._end_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        await self._prepare_trustscores_exchange(federation)

        weights = self._load_local_trustscores_weights(experiment_name)
        local_trust_report_json = await asyncio.to_thread(
            self._compute_local_trustscores_report,
            experiment_name,
            trust_config,
            weights,
            federation,
        )
        logging.info("[TW %s] local trustscores report computed", federation)

        if federation == "DFL":
            self._initialize_local_trustscores_aggregation(experiment_name)
        elif self._is_sdfl_aggregator_node():
            self._initialize_sdfl_global_trustscores_aggregation(experiment_name)

        await self._share_trustscores_report(local_trust_report_json, federation)
        await self._wait_for_trustscores_reports(federation)
        await self._wait_for_trustscores_forwarding_drain(federation)

        if federation == "DFL":
            self._finalize_local_trustscores_aggregation()
        elif self._is_sdfl_aggregator_node():
            self._finalize_sdfl_global_trustscores_aggregation()

    def _compute_local_trustscores_report(self, experiment_name, trust_config, weights, federation) -> str:
        # Build the local DFL/SDFL factsheet and return its JSON report.
        factsheet = DflFactsheet()
        self._engine.trainer.datamodule.setup(stage="fit")
        train_loader = self._engine.trainer.datamodule.train_dataloader()
        self._engine.trainer.datamodule.setup(stage="test")
        test_loader = self._engine.trainer.datamodule.test_dataloader()[0]
        factsheet.populate_factsheet_dfl(
            experiment_name,
            self._idx,
            trust_config,
            self._start_time,
            self._end_time,
            self._engine.trainer.model,
            train_loader,
            test_loader,
            reputation_summary=self._get_reputation_trust_summary(),
            participation_summary=self._get_participation_trust_summary(),
            reliability_summary=self._get_system_reliability_summary(),
        )

        trust_metric_manager = TrustMetricManager(self._start_time, federation, self._idx)
        trust_metric_manager.evaluate_participant(experiment_name, weights, self._idx, use_weights=True)

        return load_trust_report_json_dumped(experiment_name, self._idx)

    def _load_local_trustscores_weights(self, experiment_name: str) -> dict:
        # Load trust metric weights for the active federation.
        federation = self._engine.config.participant["trust_args"]["scenario"].get("federation")
        return load_trust_weights(experiment_name, federation)

    def _reset_trustscores_exchange_state(self):
        # Clear mutable state from any previous trustscores exchange.
        self._expected_trustscores_sources = set()
        self._received_trustscores_node_ids = set()
        self._trustscores_score_accumulator = {}
        self._trustscores_weight_accumulator = {}
        self._trustscores_template_report = None
        self._trustscores_local_copy_path = None
        self._trustscores_local_report_initialized = False

    def _get_trustscores_weight_for_source(self, source: str, node_id: int | str) -> float:
        # Resolve the aggregation weight for a remote trust report.
        if not self._is_reputation_enabled():
            return 0.5

        reputation_system = self._get_reputation_system()
        if reputation_system is None:
            logging.warning(
                "[TW DFL] Reputation is enabled but the reputation system is not available. Using fallback weight=0.5 for node_id=%s source=%s",
                node_id,
                source,
            )
            return 0.5

        reputation_entry = reputation_system.reputation.get(source)
        if reputation_entry is None or reputation_entry.get("reputation") is None:
            logging.warning(
                "[TW DFL] No reputation value available for node_id=%s source=%s. Using fallback weight=0.5",
                node_id,
                source,
            )
            return 0.5

        return float(reputation_entry["reputation"])

    def _get_trustscores_peer_weights_from_reputation(self) -> dict:
        # Extract peer trustscores weights from the reputation system.
        if not self._is_reputation_enabled():
            return {}

        reputation_system = self._get_reputation_system()
        if reputation_system is None:
            return {}

        peer_weights = {}
        for addr, data in reputation_system.reputation.items():
            reputation_value = data.get("reputation")
            if addr == self._engine.addr or reputation_value is None:
                continue
            peer_weights[addr] = float(reputation_value)
        return peer_weights

    def _get_trustscores_self_weight(self) -> float:
        # Keep local reports fully trusted in the weighted aggregation.
        return 1.0

    def _log_trustscores_node_weights(self, federation: str):
        # Log the weights that will be used by trustscores aggregation.
        if not self._is_reputation_enabled():
            logging.info(
                "[TW %s] Reputation system disabled. trustscores weights fallback to 0.5 for all nodes",
                federation,
            )
            return

        peer_weight_map = self._get_trustscores_peer_weights_from_reputation()
        if not peer_weight_map:
            logging.info(
                "[TW %s] Reputation system enabled, but no peer reputation weights are available yet. Falling back to 0.5 when needed",
                federation,
            )
            return

        logging.info(
            "[TW %s] Trustscores weights from reputation | self_node_id=%s self_weight=%s peer_weights_by_addr=%s",
            federation,
            self._idx,
            self._get_trustscores_self_weight(),
            peer_weight_map,
        )

        for addr, weight in sorted(peer_weight_map.items()):
            logging.info(
                "[TW %s] Trustscores weight from reputation | self_node_id=%s target_addr=%s weight=%s",
                federation,
                self._idx,
                addr,
                weight,
            )

    def _initialize_local_trustscores_aggregation(self, experiment_name: str):
        # Initialize a DFL local aggregation copy with this node's own report.
        if self._trustscores_local_report_initialized:
            return

        trust_report_template, copy_path = create_local_trust_report_copy(experiment_name, self._idx)
        self._initialize_trustscores_accumulator(trust_report_template, copy_path, self._get_trustscores_self_weight())
        logging.info(
            "[TW DFL] Local trustscores copy created at %s and accumulator initialized with local weight=%s",
            copy_path,
            self._get_trustscores_self_weight(),
        )

    async def _prepare_trustscores_exchange(self, federation: str):
        # Discover direct neighbors and prepare the wait event for incoming reports.
        cm = CommunicationsManager.get_instance()
        self._expected_trustscores_sources = await cm.get_all_addrs_current_connections(only_direct=True)

        if self._trustscores_wait_event is None:
            self._trustscores_wait_event = asyncio.Event()
        self._trustscores_wait_event.clear()

        if len(self._received_trustscores_node_ids) >= self._expected_trustscores_reports:
            self._trustscores_wait_event.set()

        if self._expected_trustscores_reports <= 0:
            self._trustscores_wait_event.set()
            logging.info("[TW %s] No remote trustscores reports expected", federation)
            return

        logging.info(
            "[TW %s] Expecting %s trustscores reports. Initial neighbors=%s aggregator_mode=%s",
            federation,
            self._expected_trustscores_reports,
            sorted(self._expected_trustscores_sources),
            self._is_sdfl_aggregator_node() if federation == "SDFL" else False,
        )
        if federation == "DFL" or self._is_sdfl_aggregator_node():
            self._log_trustscores_node_weights(federation)

    async def _share_trustscores_report(self, trust_report_json: str, federation: str):
        # Broadcast the local trustscores report to direct neighbors.
        cm = CommunicationsManager.get_instance()
        neighbors = self._expected_trustscores_sources.copy()

        if not neighbors:
            logging.info("[TW %s] No direct neighbors available to share trustscores", federation)
            return

        message = cm.create_message(
            "trustscores",
            action="share",
            node_id=str(self._idx),
            trust_report_json=trust_report_json,
        )

        logging.info("[TW %s] Sharing trustscores report with neighbors=%s", federation, sorted(neighbors))
        for neighbor in neighbors:
            await cm.send_message(
                neighbor,
                message,
                message_type="trustscores",
                allow_after_learning_finished=True,
            )

    async def _wait_for_trustscores_reports(self, federation: str):
        # Wait until every expected report arrives or the exchange times out.
        if self._trustscores_wait_event is None:
            return

        try:
            await asyncio.wait_for(
                self._trustscores_wait_event.wait(),
                timeout=self.TRUSTSCORES_WAIT_TIMEOUT_SECONDS,
            )
            logging.info(
                "[TW %s] Trustscores exchange complete (%s/%s)",
                federation,
                len(self._received_trustscores_node_ids),
                self._expected_trustscores_reports,
            )
        except asyncio.TimeoutError:
            logging.warning(
                "[TW %s] Timeout waiting trustscores reports. Received=%s/%s missing=%s",
                federation,
                len(self._received_trustscores_node_ids),
                self._expected_trustscores_reports,
                self._expected_trustscores_reports - len(self._received_trustscores_node_ids),
            )

    async def _wait_for_trustscores_forwarding_drain(self, federation: str):
        # Give the forwarder a short grace period before shutdown.
        if not self._expected_trustscores_sources:
            return

        cm = CommunicationsManager.get_instance()
        forwarder = getattr(cm, "forwarder", None)
        forwarder_interval = getattr(forwarder, "interval", 0)
        messages_interval = getattr(forwarder, "messages_interval", 0)
        forwarding_grace = max(
            self.TRUSTSCORES_FORWARDING_GRACE_SECONDS,
            float(forwarder_interval) + float(messages_interval) + self.TRUSTSCORES_FORWARDING_GRACE_MARGIN_SECONDS,
        )

        logging.info(
            "[TW %s] Waiting %.2fs to drain forwarded trustscores messages before shutdown",
            federation,
            forwarding_grace,
        )
        await asyncio.sleep(forwarding_grace)

    def _build_weighted_trustscores_report(self) -> dict | None:
        # Build the weighted report when the aggregation template is available.
        if self._trustscores_template_report is None or self._trustscores_local_copy_path is None:
            return None

        return build_weighted_trustscores_report(
            template_report=self._trustscores_template_report,
            score_accumulator=self._trustscores_score_accumulator,
            weight_accumulator=self._trustscores_weight_accumulator,
        )

    def _finalize_local_trustscores_aggregation(self):
        # Write the weighted DFL report and generate DFL graphics.
        aggregated_report = self._build_weighted_trustscores_report()
        if aggregated_report is None:
            logging.warning("[TW DFL] Skipping weighted trustscores write because local copy/template is not available")
            return

        save_trust_report_json(self._trustscores_local_copy_path, aggregated_report)
        logging.info(
            "[TW DFL] Weighted trustscores written to local copy=%s",
            self._trustscores_local_copy_path,
        )

        graphics = Graphics(self._start_time, self._experiment_name, self._idx)
        graphics.graphics_dfl_global(self._idx)

    def _finalize_sdfl_global_trustscores_aggregation(self):
        # Write the weighted SDFL global report and generate SDFL graphics.
        aggregated_report = self._build_weighted_trustscores_report()
        if aggregated_report is None:
            logging.warning("[TW SDFL] Skipping global trustscores write because the template/output is not available")
            return

        save_trust_report_json(self._trustscores_local_copy_path, aggregated_report)
        logging.info(
            "[TW SDFL] Global weighted trustscores written to %s",
            self._trustscores_local_copy_path,
        )

        graphics = Graphics(self._start_time, self._experiment_name, self._idx)
        graphics.graphics_sdfl_global(self._idx)

    def _is_sdfl_aggregator_node(self) -> bool:
        # Check whether this node should aggregate global SDFL trustscores.
        effective_role = self._engine.rb.get_role_name(True)
        return effective_role in {Role.AGGREGATOR.value, Role.TRAINER_AGGREGATOR.value}

    def _initialize_sdfl_global_trustscores_aggregation(self, experiment_name: str):
        # Initialize the SDFL global aggregation output with this node's own report.
        if self._trustscores_local_report_initialized:
            return

        trust_report_template = json.loads(load_trust_report_json_dumped(experiment_name, self._idx))
        logs_dir = os.environ.get("NEBULA_LOGS_DIR", os.path.join("nebula", "app", "logs"))
        output_path = os.path.join(
            logs_dir,
            experiment_name,
            "trustworthiness",
            "nebula_trust_results.json",
        )
        save_trust_report_json(output_path, trust_report_template)

        self._initialize_trustscores_accumulator(trust_report_template, output_path, self._get_trustscores_self_weight())
        logging.info(
            "[TW SDFL] Global trustscores accumulator initialized at %s with local weight=1.0",
            output_path,
        )

    def _initialize_trustscores_accumulator(self, trust_report_template: dict, output_path: str, local_weight: float):
        # Store the aggregation template and seed accumulators with the local report.
        self._trustscores_template_report = trust_report_template
        self._trustscores_local_copy_path = output_path
        accumulate_weighted_trustscores(
            report=trust_report_template,
            weight=local_weight,
            score_accumulator=self._trustscores_score_accumulator,
            weight_accumulator=self._trustscores_weight_accumulator,
        )
        self._trustscores_local_report_initialized = True

    async def register_trustscores_report(self, source, message):
        # Register a remote trustscores message using the active federation.
        federation = self._engine.config.participant["trust_args"]["scenario"].get("federation")
        await self._register_trustscores_report(source, message, federation)

    async def _register_trustscores_report(self, source, message, federation: str):
        # Deduplicate, optionally accumulate, and mark remote trustscores as received.
        if str(message.node_id) == str(self._idx):
            logging.info("[TW %s] Ignoring own trustscores report from %s", federation, source)
            return

        if str(message.node_id) in self._received_trustscores_node_ids:
            logging.info(
                "[TW %s] Ignoring duplicated trustscores report from node_id=%s source=%s",
                federation,
                message.node_id,
                source,
            )
            return

        should_accumulate = federation == "DFL" or self._is_sdfl_aggregator_node()
        if should_accumulate:
            trust_report = json.loads(message.trust_report_json)
            remote_weight = self._get_trustscores_weight_for_source(source, message.node_id)
            accumulate_weighted_trustscores(
                report=trust_report,
                weight=remote_weight,
                score_accumulator=self._trustscores_score_accumulator,
                weight_accumulator=self._trustscores_weight_accumulator,
            )
            logging.info(
                "[TW %s] Trustscores report received from node_id=%s source=%s accumulated_with_weight=%s",
                federation,
                message.node_id,
                source,
                remote_weight,
            )
        else:
            logging.info(
                "[TW %s] Trustscores report received from node_id=%s source=%s forwarding_only=True",
                federation,
                message.node_id,
                source,
            )

        self._received_trustscores_node_ids.add(str(message.node_id))
        logging.info(
            "[TW %s] Trustscores progress %s/%s",
            federation,
            len(self._received_trustscores_node_ids),
            self._expected_trustscores_reports,
        )
        if len(self._received_trustscores_node_ids) >= self._expected_trustscores_reports:
            self._trustscores_wait_event.set()

class TrustWorkloadServer(BaseTrustWorkload):
    REPORTS_WAIT_TIMEOUT_SECONDS = 60

    def __init__(self, engine: Engine, idx, trust_files_route):
        # Initialize server-side state for collecting participant reports.
        server_start_time: ServerRoleBehavior = engine.rb
        super().__init__(
            engine,
            idx,
            trust_files_route,
            workload="aggregation",
            role_label="SERVER",
            sample_size=0,
            start_time=server_start_time._start_time,
        )
        self._trustworthiness_reports = {}
        self._expected_reports = int(self._engine.config.participant["scenario_args"]["n_nodes"])-1
        self._trust_config = None
        self._csv_completed = False
        self._reports_wait_event = asyncio.Event()
        if self._expected_reports <= 0:
            self._reports_wait_event.set()

    async def init(self, experiment_name):
        # Reuse the shared workload event subscriptions.
        await super().init(experiment_name)

    async def finish_experiment_role_pre_actions(self):
        # Server has no pre-save work because aggregation sample size is zero.
        pass

    async def finish_experiment_role_post_actions(self, trust_config, experiment_name):
        # Wait for participant reports, save CSV data, and generate the CFL factsheet.
        self._end_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        self._trust_config = trust_config
        self._experiment_name = experiment_name

        if self._csv_completed:
            logging.info("[TW SERVER] finish_experiment_role_post_actions called, trustworthiness reports OK, starting generate_factsheet")
            await self._save_local_server_report_and_generate_factsheet(trust_config, experiment_name)
            return

        logging.info("[TW SERVER] finish_experiment_role_post_actions called, waiting for trustworthiness reports")
        await self._wait_for_trustworthiness_reports()
        self._save_trustworthiness_reports_once()
        await self._save_local_server_report_and_generate_factsheet(trust_config, experiment_name)

    async def _wait_for_trustworthiness_reports(self):
        # Wait until reports arrive or the server-side timeout expires.
        try:
            await asyncio.wait_for(
                self._reports_wait_event.wait(),
                timeout=self.REPORTS_WAIT_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            logging.warning(
                "[TW SERVER] Timeout waiting trustworthiness reports. Received=%s/%s",
                len(self._trustworthiness_reports),
                self._expected_reports,
            )

    def _save_trustworthiness_reports_once(self):
        # Persist received participant reports only once.
        if self._trustworthiness_reports is not None and not self._csv_completed:
            save_trustworthiness_reports_csv(self._trustworthiness_reports, self._experiment_name)
            self._csv_completed = True

    async def _save_local_server_report_and_generate_factsheet(self, trust_config, experiment_name):
        # Add the server's own local report and generate final trust artifacts.
        bytes_sent, bytes_recv, _, _, val_accuracy, _, _, dp_enabled, dp_epsilon = load_data_results_participant(
            self._experiment_name,
            self._idx,
        )

        role, energy_grid, emissions, workload, cpu_model, gpu_model, cpu_used, gpu_used, energy_consumed, sample_size = load_emissions_participant(
            self._experiment_name,
            self._idx,
        )

        logging.info(
            "[TW SERVER] local server report added for node_id=%s",
            str(self._idx),
        )

        class_imbalance = get_class_imbalance_local(self._idx, experiment_name)
        model_size = get_bytes_model(self._engine.trainer.model)
        local_entropy = get_local_entropy(self._idx, experiment_name)

        save_results_csv_cfl(self._experiment_name, self._idx, bytes_sent, bytes_recv, 0, 0, class_imbalance, model_size, local_entropy, val_accuracy, 0, 0, dp_enabled, dp_epsilon)
        save_emissions_csv_cfl(self._experiment_name, self._idx, role, energy_grid, emissions, workload, cpu_model, gpu_model, cpu_used, gpu_used, energy_consumed, sample_size)
        await self._generate_factsheet(trust_config, experiment_name)

    async def register_trustworthiness_report(self, source, message):
        # Store one participant trustworthiness report received by the server.
        self._trustworthiness_reports[message.node_id] = {
            "source": source,
            "node_id": message.node_id,
            "bytes_sent": message.bytes_sent,
            "bytes_recv": message.bytes_recv,
            "accuracy": message.accuracy,
            "loss": message.loss,
            "role": message.role,
            "energy_grid": message.energy_grid,
            "emissions": message.emissions,
            "workload": message.workload,
            "cpu_model": message.cpu_model,
            "gpu_model": message.gpu_model,
            "cpu_used": message.cpu_used,
            "gpu_used": message.gpu_used,
            "energy_consumed": message.energy_consumed,
            "sample_size": message.sample_size,
            "class_imbalance": message.class_imbalance,
            "model_size": message.model_size,
            "local_entropy": message.local_entropy,
            "val_accuracy": message.val_accuracy,
            "dp_enabled": message.dp_enabled,
            "dp_epsilon": message.dp_epsilon,
            "macro_f1": message.macro_f1,
            "train_accuracy": message.train_accuracy,
        }

        logging.info(
            "[TW SERVER] received report from node_id=%s total=%s",
            message.node_id,
            len(self._trustworthiness_reports),
        )

        if (len(self._trustworthiness_reports) >= self._expected_reports):
            logging.info("[TW SERVER] all reports received, generating csv")
            self._save_trustworthiness_reports_once()
            self._reports_wait_event.set()
            logging.info(f"[TW SERVER] all reports received, waiting for finish post, csv_completed {self._csv_completed}")

    async def _generate_factsheet(self, trust_config, experiment_name):
        # Generate the CFL factsheet and evaluate final trust metrics.
        factsheet = CflFactsheet()
        self._engine.trainer.datamodule.setup(stage="fit")
        train_loader = self._engine.trainer.datamodule.train_dataloader()
        self._engine.trainer.datamodule.setup(stage="test")
        test_loader = self._engine.trainer.datamodule.test_dataloader()[0]
        factsheet.populate_factsheet_cfl(
            experiment_name,
            trust_config,
            self._start_time,
            self._end_time,
            self._idx,
            self._engine.trainer.model,
            train_loader,
            test_loader,
            reputation_summary=self._get_reputation_trust_summary(),
            participation_summary=self._get_participation_trust_summary(),
            reliability_summary=self._get_system_reliability_summary(),
        )

        federation = trust_config.get("federation")
        weights = load_trust_weights(experiment_name, federation)

        trust_metric_manager = TrustMetricManager(self._start_time, federation)
        trust_metric_manager.evaluate(experiment_name, weights, use_weights=True)

"""                                                     ##############################
                                                        #       TRUSTWORTHINESS      #
                                                        ##############################
"""

class Trustworthiness():
    def __init__(self, engine: Engine, config: Config):
        # Select the workload implementation for this node and start emissions tracking.
        config.reset_logging_configuration()
        print_msg_box(
            msg=f"Name Trustworthiness Module\nRole: {engine.rb.get_role_name()}",
            indent=2,
        )
        self._engine = engine
        self._config = config
        self._trust_config = self._config.participant["trust_args"]["scenario"]
        self._experiment_name = self._config.participant["scenario_args"]["name"]
        logs_dir = os.environ.get("NEBULA_LOGS_DIR", os.path.join("nebula", "app", "logs"))
        self._trust_dir_files = os.path.join(logs_dir, self._experiment_name, "trustworthiness")
        self._emissions_file = 'emissions.csv'
        self._role: Role = engine.rb.get_role()
        self._idx = self._config.participant["device_args"]["idx"]
        self._trust_workload: TrustWorkload = self._factory_trust_workload(self._role, self._engine, self._idx, self._trust_dir_files)

        self._engine.trustworthiness = self

        # EmissionsTracker from CodeCarbon to measure emissions during the server aggregation step
        self._tracker= EmissionsTracker(tracking_mode='process', log_level='error', save_to_file=False)

    @property
    def tw(self):
        """TrustWorkload implementation chosen according to the node role."""
        # Expose the role-specific trust workload.
        return self._trust_workload

    async def start(self):
        # Prepare output directories, subscribe to finish events, and start tracking emissions.
        await self._create_trustworthiness_directory()
        await self.tw.init(self._experiment_name)
        await EventManager.get_instance().subscribe_node_event(ExperimentFinishEvent, self._process_experiment_finish_event)
        self._tracker.start()

    async def _create_trustworthiness_directory(self):
        # Ensure the experiment trustworthiness directory exists.
        logs_dir = os.environ.get("NEBULA_LOGS_DIR", os.path.join("nebula", "app", "logs"))
        trust_dir = os.path.join(logs_dir, self._experiment_name, "trustworthiness")
        # Create a directory to store files used to compute trust
        os.makedirs(trust_dir, exist_ok=True)
        os.chmod(trust_dir, 0o755)

    async def _process_experiment_finish_event(self, efe: ExperimentFinishEvent):
        # Persist final local metrics and delegate role-specific finalization.
        class_counter = self._engine.trainer.datamodule.get_samples_per_label()

        save_class_count_per_participant(self._experiment_name, class_counter, self._idx)

        await self.tw.finish_experiment_role_pre_actions()

        last_loss, last_accuracy, last_macro_f1 = self.tw.get_metrics()
        _, last_val_accuracy, last_train_accuracy = self.tw.get_validation_metrics()
        if last_val_accuracy is None:
            last_val_accuracy = 0.0

        # Get sent/received bytes from the reporter
        bytes_sent = self._engine.reporter.acc_bytes_sent
        bytes_recv = self._engine.reporter.acc_bytes_recv

        # Persist the trainer-reported DP budget so factsheets can score privacy.
        privacy_metrics = self._engine.trainer.get_privacy_metrics()
        dp_enabled=bool(privacy_metrics.get("dp_enabled", False))
        dp_epsilon=privacy_metrics.get("dp_epsilon")
        if dp_epsilon is None:
            dp_epsilon=0

        # Get TrustWorkload information
        workload = self.tw.get_workload()
        sample_size = self.tw.get_sample_size()

        # Final operations
        save_results_csv(
            self._experiment_name,
            self._idx,
            bytes_sent,
            bytes_recv,
            last_accuracy,
            last_loss,
            last_val_accuracy,
            last_macro_f1,
            last_train_accuracy,
            dp_enabled,
            dp_epsilon,
        )
        stop_emissions_tracking_and_save(self._tracker, self._trust_dir_files, f'emissions_{self._idx}.csv', self._role.value, workload, sample_size, self._idx)
        await self.tw.finish_experiment_role_post_actions(self._trust_config, self._experiment_name)

    def _factory_trust_workload(self, role: Role, engine: Engine, idx, trust_files_route) -> TrustWorkload:
        # Create the workload implementation associated with the node role.
        trust_workloads = {
            Role.TRAINER: TrustWorkloadTrainer,
            Role.AGGREGATOR: TrustWorkloadTrainer,
            Role.PROXY: TrustWorkloadTrainer,
            Role.IDLE: TrustWorkloadTrainer,
            Role.TRAINER_AGGREGATOR: TrustWorkloadTrainer,
            Role.MALICIOUS: TrustWorkloadTrainer,
            Role.SERVER: TrustWorkloadServer
        }
        trust_workload = trust_workloads.get(role)
        if trust_workload:
            return trust_workload(engine, idx, trust_files_route)
        else:
            raise TrustWorkloadException(f"Trustworthiness workload for role {role} not defined")
