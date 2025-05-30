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

"""                                                     ##############################
                                                        #       TRUST WORKLOADS      #
                                                        ##############################
"""

class TrustWorkloadException(Exception):
    pass

class TrustWorkload(ABC):
    @abstractmethod
    async def init(self):
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
    async def finish_experiment_role_actions(self):
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
        
    async def init(self):
        await EventManager.get_instance().subscribe_node_event(RoundEndEvent, self._process_round_end_event)
        await EventManager.get_instance().subscribe_addonevent(TestMetricsEvent, self._process_test_metrics_event)
        
    def get_workload(self):
        return self._workload
    
    def get_sample_size(self):
        return self._sample_size
    
    def get_metrics(self):
        return (self._current_loss, self._current_accuracy)
    
    async def finish_experiment_role_actions(self):
        with open(self._train_loader_file, 'rb') as file:
            train_loader = pickle.load(file)
        self._sample_size = len(train_loader)
        
    async def _process_round_end_event(self, ree: RoundEndEvent):
        scenario_name = self._engine.config.participant["scenario_args"]["name"]
        train_model = f"/nebula/app/logs/{scenario_name}/trustworthiness/participant_{self._idx}_train_model.pk"
        # Save the train model in trustworthy dir
        with open(train_model, 'wb') as f:
            pickle.dump(self._engine.trainer.model, f)
        pass
    
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
        
    async def init(self):
        await EventManager.get_instance().subscribe_addonevent(TestMetricsEvent, self._process_test_metrics_event)   
        
    def get_workload(self):
        return self._workload
    
    def get_sample_size(self):
        return self._sample_size
    
    def get_metrics(self):
        return (self._current_loss, self._current_accuracy)
    
    async def finish_experiment_role_actions(self):
        pass
    
    async def _process_test_metrics_event(self, tme: TestMetricsEvent):
        cur_loss, cur_acc = await tme.get_event_data()
        if cur_loss and cur_acc:
            self._current_loss, self._current_accuracy = cur_loss, cur_acc

"""                                                     ##############################
                                                        #       TRUSTWORTHINESS      #
                                                        ##############################
"""
#TODO need trainer.test() to return loss,accuracy -> create TestMetricsEvent
#TODO cambiar en engine para q trabaje con Role de role.py

class Trustworthiness():
    def _init_(self, engine: Engine, config: Config):
        self._engine = engine
        self._config = config
        self._trust_dir_files = f"/nebula/app/logs/{self._experiment_name}/trustworthiness"
        self._experiment_name = self._config.participant["scenario_args"]["name"]
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
        await EventManager.get_instance().subscribe_node_event(ExperimentFinishEvent, self._process_experiment_finish_event)
        self._tracker.start()
        
    async def _process_experiment_finish_event(self, efe: ExperimentFinishEvent):
        last_loss, last_accuracy = self.tw.get_metrics()
        
        # Save model -> neccesary here?
        # model_file = f"/nebula/app/logs/{self._experiment_name}/trustworthiness/participant_{self._idx}_final_model.pk"
        # with open(model_file, 'wb') as f:
        #     pickle.dump(self._engine.trainer.model, f)
            
        # Get bytes send/received from reporter
        bytes_sent = self._engine.reporter.acc_bytes_sent
        bytes_recv = self._engine.reporter.acc_bytes_recv
        
        # Get TrustWorkload info
        await self.tw.finish_experiment_role_actions()
        workload = self.tw.get_workload()
        sample_size = self.tw.get_sample_size()
        
        # Last operations
        save_results_csv(self._experiment_name, self._idx, bytes_sent, bytes_recv, last_loss, last_accuracy)
        stop_emissions_tracking_and_save(self._tracker, self._trust_dir_files, self._emissions_file, self._role.value, workload, sample_size)

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
    
    