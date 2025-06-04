import logging
from nebula.addons.functions import print_msg_box
from nebula.core.nebulaevents import ExperimentFinishEvent, RoundEndEvent, TestMetricsEvent
from nebula.core.eventmanager import EventManager
from nebula.core.role import Role
from abc import ABC, abstractmethod
from nebula.config.config import Config
from nebula.core.engine import Engine
import pickle
from nebula.addons.trustworthiness.calculation import stop_emissions_tracking_and_save
from nebula.addons.trustworthiness.utils import save_results_csv
from codecarbon import EmissionsTracker
import asyncio

"""                                                     ##############################
                                                        #       TRUST WORKLOADS      #
                                                        ##############################
"""

class TrustWorkloadException(Exception):
    pass

class TrustWorkload(ABC):
    @abstractmethod
    async def init(self, experiment_name):
        raise NotImplementedError
    
    @abstractmethod
    def get_workload(self) -> str:
        raise NotImplementedError
    
    @abstractmethod
    def get_sample_size(self) -> float:
        raise NotImplementedError
    
    abstractmethod
    def get_metrics(self) -> tuple[float, float]:
        raise NotImplementedError
    
    @abstractmethod
    async def finish_experiment_role_pre_actions(self):
        raise NotImplementedError
    
    @abstractmethod
    async def finish_experiment_role_post_actions(self, trust_config, experiment_name):
        raise NotImplementedError

class TrustWorkloadTrainer(TrustWorkload):
    def __init__(self, engine, idx, trust_files_route):
        self._engine: Engine = engine
        self._workload = 'training'
        self._idx = idx
        self._trust_files_route = trust_files_route
        self._train_loader_file = f'{self._trust_files_route}/participant_{self._idx}_train_loader.pk'
        self._sample_size = None
        self._current_loss = None
        self._current_accuracy = None
        
    async def init(self, experiment_name):
        await EventManager.get_instance().subscribe_node_event(RoundEndEvent, self._process_round_end_event)
        await EventManager.get_instance().subscribe_addonevent(TestMetricsEvent, self._process_test_metrics_event)
        await self._create_pk_files(experiment_name)
            
    async def _create_pk_files(self, experiment_name):
        # Save data to local files to calculate the trustworthyness
        train_loader_filename = f"/nebula/app/logs/{experiment_name}/trustworthiness/participant_{self._idx}_train_loader.pk"
        test_loader_filename = f"/nebula/app/logs/{experiment_name}/trustworthiness/participant_{self._idx}_test_loader.pk"
        self._engine.trainer.datamodule.setup(stage="fit")
        train_loader = self._engine.trainer.datamodule.train_dataloader()
        self._engine.trainer.datamodule.setup(stage="test")
        test_loader = self._engine.trainer.datamodule.test_dataloader()[0]
        
        with open(train_loader_filename, 'wb') as f:
            pickle.dump(train_loader, f)
            f.close()
        with open(test_loader_filename, 'wb') as f:
            pickle.dump(test_loader, f)
            f.close()
        
    def get_workload(self):
        return self._workload
    
    def get_sample_size(self):
        return self._sample_size
    
    def get_metrics(self):
        return (self._current_loss, self._current_accuracy)
    
    async def finish_experiment_role_pre_actions(self):
        with open(self._train_loader_file, 'rb') as file:
            train_loader = pickle.load(file)
        self._sample_size = len(train_loader)
        
    async def finish_experiment_role_post_action(self, trust_config, experiment_name):
        pass
        
    async def _process_round_end_event(self, ree: RoundEndEvent):
        scenario_name = self._engine.config.participant["scenario_args"]["name"]
        train_model = f"/nebula/app/logs/{scenario_name}/trustworthiness/participant_{self._idx}_train_model.pk"
        # Save the train model in trustworthy dir
        with open(train_model, 'wb') as f:
            pickle.dump(self._engine.trainer.model, f)
    
    async def _process_test_metrics_event(self, tme: TestMetricsEvent):
        cur_loss, cur_acc = await tme.get_event_data()
        if cur_loss and cur_acc:
            self._current_loss, self._current_accuracy = cur_loss, cur_acc
    
class TrustWorkloadServer(TrustWorkload):
    
    def __init__(self,  engine, idx, trust_files_route):
        self._workload = 'aggregation'
        self._sample_size = 0
        self._current_loss = None
        self._current_accuracy = None
        self._start_time = engine._start_time
        self._end_time = None
        
    async def init(self, experiment_name):
        await EventManager.get_instance().subscribe_addonevent(TestMetricsEvent, self._process_test_metrics_event)   
        
    def get_workload(self):
        return self._workload
    
    def get_sample_size(self):
        return self._sample_size
    
    def get_metrics(self):
        return (self._current_loss, self._current_accuracy)
    
    async def finish_experiment_role_pre_actions(self):
        pass
    
    async def finish_experiment_role_post_actions(self, trust_config, experiment_name):
        from datetime  import datetime
        self._end_time = datetime.now().strftime("%d/%m/%Y %H:%M:%S")
        await self._generate_factsheet(trust_config, experiment_name)
        
    async def _generate_factsheet(self, trust_config, experiment_name):
        from nebula.addons.trustworthiness.factsheet import Factsheet
        from nebula.addons.trustworthiness.metric import TrustMetricManager
        import json
        import os
        
        factsheet = Factsheet()
        factsheet.populate_factsheet_pre_train(trust_config, experiment_name)
        factsheet.populate_factsheet_post_train(experiment_name, self._start_time, self._end_time)
        
        data_file_path = os.path.join(os.environ.get('NEBULA_CONFIG_DIR'), experiment_name, "scenario.json")
        with open(data_file_path, 'r') as data_file:
            data = json.load(data_file)

            weights = {
                "robustness": float(data["robustness_pillar"]),
                "resilience_to_attacks": float(data["resilience_to_attacks"]),
                "algorithm_robustness": float(data["algorithm_robustness"]),
                "client_reliability": float(data["client_reliability"]),
                "privacy": float(data["privacy_pillar"]),
                "technique": float(data["technique"]),
                "uncertainty": float(data["uncertainty"]),
                "indistinguishability": float(data["indistinguishability"]),
                "fairness": float(data["fairness_pillar"]),
                "selection_fairness": float(data["selection_fairness"]),
                "performance_fairness": float(data["performance_fairness"]),
                "class_distribution": float(data["class_distribution"]),
                "explainability": float(data["explainability_pillar"]),
                "interpretability": float(data["interpretability"]),
                "post_hoc_methods": float(data["post_hoc_methods"]),
                "accountability": float(data["accountability_pillar"]),
                "factsheet_completeness":  float(data["factsheet_completeness"]),
                "architectural_soundness": float(data["architectural_soundness_pillar"]),
                "client_management": float(data["client_management"]),
                "optimization": float(data["optimization"]),
                "sustainability": float(data["sustainability_pillar"]),
                "energy_source": float(data["energy_source"]),
                "hardware_efficiency": float(data["hardware_efficiency"]),
                "federation_complexity": float(data["federation_complexity"])
            }

            trust_metric_manager = TrustMetricManager(self._start_time)
            trust_metric_manager.evaluate(experiment_name, weights, use_weights=True)
    
    async def _process_test_metrics_event(self, tme: TestMetricsEvent):
        cur_loss, cur_acc = await tme.get_event_data()
        if cur_loss and cur_acc:
            self._current_loss, self._current_accuracy = cur_loss, cur_acc

"""                                                     ##############################
                                                        #       TRUSTWORTHINESS      #
                                                        ##############################
"""

class Trustworthiness():
    def __init__(self, engine: Engine, config: Config):
        print_msg_box(
            msg=f"Name Trustworthiness Module\nRole: {engine.role.value}",
            indent=2,
        )
        self._engine = engine
        self._config = config
        self._trust_config = self._config.participant["trust_args"]["scenario"]
        self._experiment_name = self._config.participant["scenario_args"]["name"]
        self._trust_dir_files = f"/nebula/app/logs/{self._experiment_name}/trustworthiness"
        self._emissions_file = 'emissions.csv'
        self._role: Role = engine.role
        self._idx = self._config.participant["device_args"]["idx"]
        self._trust_workload: TrustWorkload = self._factory_trust_workload(self._role, self._engine, self._idx, self._trust_dir_files)       
        
        # EmissionsTracker from codecarbon to measure the emissions during the aggregation step in the server
        self._tracker= EmissionsTracker(tracking_mode='process', log_level='error', save_to_file=False)
        
    @property
    def tw(self):
        """TrustWorkload depending on the node Role"""
        return self._trust_workload
    
    async def start(self):
        await self._create_trustworthiness_directory()
        await EventManager.get_instance().subscribe_node_event(ExperimentFinishEvent, self._process_experiment_finish_event)
        await self.tw.init(self._experiment_name)
        logging.info("before trackker")
        self._tracker.start()
        logging.info("after trackker")
        
    async def _create_trustworthiness_directory(self):
        import os
        logging.info("log1")
        trust_dir = os.path.join(os.environ.get("NEBULA_LOGS_DIR"), self._experiment_name, "trustworthiness")
        # Create a directory to save files to calcutate trust
        os.makedirs(trust_dir, exist_ok=True)
        os.chmod(trust_dir, 0o777)
        logging.info("log2")
        
    async def _process_experiment_finish_event(self, efe: ExperimentFinishEvent):
        await self.tw.finish_experiment_role_pre_actions()
        
        last_loss, last_accuracy = self.tw.get_metrics()
        
        # Save model -> neccesary here?
        # model_file = f"/nebula/app/logs/{self._experiment_name}/trustworthiness/participant_{self._idx}_final_model.pk"
        # with open(model_file, 'wb') as f:
        #     pickle.dump(self._engine.trainer.model, f)
            
        # Get bytes send/received from reporter
        bytes_sent = self._engine.reporter.acc_bytes_sent
        bytes_recv = self._engine.reporter.acc_bytes_recv
        
        # Get TrustWorkload info
        workload = self.tw.get_workload()
        sample_size = self.tw.get_sample_size()
        
        # Last operations
        save_results_csv(self._experiment_name, self._idx, bytes_sent, bytes_recv, last_loss, last_accuracy)
        stop_emissions_tracking_and_save(self._tracker, self._trust_dir_files, self._emissions_file, self._role.value, workload, sample_size)
        asyncio.sleep(30)
        await self.tw.finish_experiment_role_post_actions(self._trust_config, self._experiment_name)

    def _factory_trust_workload(self, role: Role, engine: Engine, idx, trust_files_route) -> TrustWorkload:  
        trust_workloads = {
            Role.TRAINER: TrustWorkloadTrainer, 
            Role.SERVER: TrustWorkloadServer
        }
        trust_workload = trust_workloads.get(role)
        if trust_workload:
            return trust_workload(engine, idx, trust_files_route)
        else:
            raise TrustWorkloadException(f"Trustworthiness workload for role {role} not defined")
    
    