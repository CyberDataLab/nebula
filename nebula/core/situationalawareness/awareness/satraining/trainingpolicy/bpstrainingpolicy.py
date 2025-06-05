from nebula.core.situationalawareness.awareness.satraining.trainingpolicy.trainingpolicy import TrainingPolicy
from nebula.core.situationalawareness.awareness.suggestionbuffer import SuggestionBuffer
from nebula.core.situationalawareness.awareness.sautils.sacommand import SACommand, factory_sa_command, SACommandAction, SACommandPRIO
from nebula.core.nebulaevents import RoundEndEvent

class BPSTrainingPolicy(TrainingPolicy):
    
    def __init__(self, config=None):
        pass
    
    async def init(self, config):
        await self.register_sa_agent()    

    async def get_evaluation_results(self):
        sac = factory_sa_command(
            "connectivity",
            SACommandAction.MAINTAIN_CONNECTIONS,
            self, 
            "",
            SACommandPRIO.LOW,
            False,
            None,
            None
        )
        await self.suggest_action(sac)
        await self.notify_all_suggestions_done(RoundEndEvent)
    
    async def get_agent(self) -> str:
        return "SATraining_BPSTP"

    async def register_sa_agent(self):
        await SuggestionBuffer.get_instance().register_event_agents(RoundEndEvent, self)
    
    async def suggest_action(self, sac : SACommand):
        await SuggestionBuffer.get_instance().register_suggestion(RoundEndEvent, self, sac)
    
    async def notify_all_suggestions_done(self, event_type):
        await SuggestionBuffer.get_instance().notify_all_suggestions_done_for_agent(self, event_type)