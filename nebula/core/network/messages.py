import logging
from nebula.core.pb import nebula_pb2
from datetime import datetime

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula.core.network.communications import CommunicationsManager


class MessagesManager:
    def __init__(self, addr, config, cm: "CommunicationsManager"):
        self.addr = addr
        self.config = config
        self.cm = cm

    def generate_discovery_message(self, action, latitude=0.0, longitude=0.0):
        message = nebula_pb2.DiscoveryMessage(
            action=action,
            latitude=latitude,
            longitude=longitude,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.discovery_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data

    def generate_control_message(self, action, log="Control message", time=None):
        message = nebula_pb2.ControlMessage(
            action=action,
            log=log,
            time=time,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.control_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data

    def generate_federation_message(self, action, arguments=[], round=None):
        logging.info(f"Building federation message with [Action {action}], arguments {arguments}, and round {round}")

        message = nebula_pb2.FederationMessage(
            action=action,
            arguments=[str(arg) for arg in (arguments or [])],
            round=round,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.federation_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data

    def generate_model_message(self, round, serialized_model, weight=1):
        message = nebula_pb2.ModelMessage(
            round=round,
            parameters=serialized_model,
            weight=weight,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.model_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data

    def generate_connection_message(self, action):
        message = nebula_pb2.ConnectionMessage(
            action=action,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.connection_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data

    """def generate_reputation_message(self, reputation):
        message = nebula_pb2.ReputationMessage(
            reputation=reputation,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.reputation_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data"""
    
    def generate_reputation_message(self, node_id, score, round):
        message = nebula_pb2.ReputationMessage(
            node_id=node_id,
            score=score,
            round=round,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.reputation_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data
    
    def generate_flood_attack_message(self, attacker_id, frequency, duration, target_node):
        message = nebula_pb2.FloodAttackMessage(
            attacker_id=attacker_id,
            frequency=frequency,
            duration=duration,
            target_node=target_node,
        )
        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        message_wrapper.flood_attack_message.CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data
    
    
