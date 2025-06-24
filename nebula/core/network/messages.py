import hashlib
import logging
import traceback

from nebula.core.nebulaevents import MessageEvent
from nebula.core.network.actions import factory_message_action, get_action_name_from_value, get_actions_names
from nebula.core.pb import nebula_pb2


class MessagesManager:
    """
    Manages creation, processing, and whenever is neccesary to do forwarding of Nebula protobuf messages.
    Handles different message types defined in the protocol and coordinates with the CommunicationsManager.
    """

    def __init__(self, addr, config):
        """
        Initialize MessagesManager with the node address and configuration.

        Args:
            addr (str): The network address of the current node.
            config (dict): Configuration dictionary for the node.
        """
        self.addr = addr
        self.config = config
        self._cm = None
        self._message_templates = {}
        self._define_message_templates()

    @property
    def cm(self):
        """
        Lazy-load and return the singleton instance of CommunicationsManager.

        Returns:
            CommunicationsManager: The communications manager instance.
        """
        if not self._cm:
            from nebula.core.network.communications import CommunicationsManager

            self._cm = CommunicationsManager.get_instance()
            return self._cm
        else:
            return self._cm

    def _define_message_templates(self):
        """
        Define the message templates mapping message types to their parameters and default values.
        This is used to dynamically create messages of different types.
        """
        # Dictionary that maps message types to their required parameters and default values
        self._message_templates = {
            "offer": {
                "parameters": ["action", "n_neighbors", "loss", "parameters", "rounds", "round", "epochs"],
                "defaults": {
                    "parameters": None,
                    "rounds": 1,
                    "round": -1,
                    "epochs": 1,
                },
            },
            "connection": {"parameters": ["action"], "defaults": {}},
            "discovery": {
                "parameters": ["action", "latitude", "longitude"],
                "defaults": {
                    "latitude": 0.0,
                    "longitude": 0.0,
                },
            },
            "control": {
                "parameters": ["action", "log"],
                "defaults": {
                    "log": "Control message",
                },
            },
            "federation": {
                "parameters": ["action", "arguments", "round"],
                "defaults": {
                    "arguments": [],
                    "round": None,
                },
            },
            "model": {
                "parameters": ["round", "parameters", "weight"],
                "defaults": {
                    "weight": 1,
                },
            },
            "reputation": {
                "parameters": ["node_id", "score", "round", "action"],
                "defaults": {
                    "round": None,
                },
            },
            "discover": {"parameters": ["action"], "defaults": {}},
            "link": {"parameters": ["action", "addrs"], "defaults": {}},
            # Add additional message types here
        }

    def get_messages_events(self) -> dict:
        """
        Retrieve the available message event names and their corresponding actions.

        Returns:
            dict: Mapping of message names (excluding 'model') to their available action names.
        """
        message_events = {}
        for message_name in self._message_templates:
            if message_name != "model":
                message_events[message_name] = get_actions_names(message_name)
        return message_events

    async def process_message(self, data, addr_from):
        """
        Asynchronously process an incoming serialized protobuf message.

        Parses the message, verifies source, forwards or handles the message depending on its type,
        and prevents duplicate processing using message hashes.

        Args:
            data (bytes): Serialized protobuf message bytes.
            addr_from (str): Address from which the message was received.
        """
        not_processing_messages = {"control_message", "connection_message"}
        special_processing_messages = {"discovery_message", "federation_message", "model_message"}

        try:
            message_wrapper = nebula_pb2.Wrapper()
            message_wrapper.ParseFromString(data)
            source = message_wrapper.source
            logging.debug(f"📥  handle_incoming_message | Received message from {addr_from} with source {source}")
            if source == self.addr:
                return

            # Extract the active message from the oneof field
            message_type = message_wrapper.WhichOneof("message")
            msg_name = message_type.split("_")[0]
            if not message_type:
                logging.warning("Received message with no active field in the 'oneof'")
                return

            message_data = getattr(message_wrapper, message_type)

            # Not required processing messages
            if message_type in not_processing_messages:
                # await self.cm.handle_message(source, message_type, message_data)
                me = MessageEvent(
                    (msg_name, get_action_name_from_value(msg_name, message_data.action)), source, message_data
                )
                await self.cm.handle_message(me)

            # Message-specific forwarding and processing
            elif message_type in special_processing_messages:
                if await self.cm.include_received_message_hash(hashlib.md5(data).hexdigest(), addr_from):
                    # Forward the message if required
                    if self._should_forward_message(message_type, message_wrapper):
                        await self.cm.forward_message(data, addr_from)

                    if message_type == "model_message":
                        await self.cm.handle_model_message(source, message_data)
                    else:
                        me = MessageEvent(
                            (msg_name, get_action_name_from_value(msg_name, message_data.action)), source, message_data
                        )
                        await self.cm.handle_message(me)
            # Rest of messages
            else:
                # if await self.cm.include_received_message_hash(hashlib.md5(data).hexdigest()):
                me = MessageEvent(
                    (msg_name, get_action_name_from_value(msg_name, message_data.action)), source, message_data
                )
                await self.cm.handle_message(me)
        except Exception as e:
            logging.exception(f"📥  handle_incoming_message | Error while processing: {e}")
            logging.exception(traceback.format_exc())

    def _should_forward_message(self, message_type, message_wrapper):
        """
        Determine if a received message should be forwarded to other nodes.

        Forwarding is enabled for proxy devices or for specific message types
        like initialization model messages or federation start actions.

        Args:
            message_type (str): Type of the message, e.g. 'model_message'.
            message_wrapper (nebula_pb2.Wrapper): Parsed protobuf wrapper message.

        Returns:
            bool: True if the message should be forwarded, False otherwise.
        """
        if self.cm.config.participant["device_args"]["proxy"]:
            return True
        # TODO: Improve the technique. Now only forward model messages if the node is a proxy
        # Need to update the expected model messages receiving during the round
        # Round -1 is the initialization round --> all nodes should receive the model
        if message_type == "model_message" and message_wrapper.model_message.round == -1:
            return True
        if (
            message_type == "federation_message"
            and message_wrapper.federation_message.action
            == nebula_pb2.FederationMessage.Action.Value("FEDERATION_START")
        ):
            return True

    def create_message(self, message_type: str, action: str = "", *args, **kwargs):
        """
        Create and serialize a protobuf message of the given type and action.

        Dynamically maps provided arguments to the protobuf message fields using predefined templates.
        Wraps the message in a Nebula 'Wrapper' message with the node's address as source.

        Args:
            message_type (str): The type of message to create (e.g. 'offer', 'model', etc.).
            action (str, optional): Action name for the message, converted to protobuf enum. Defaults to "".
            *args: Positional arguments for message fields according to the template.
            **kwargs: Keyword arguments for message fields.

        Raises:
            ValueError: If the message_type is invalid.
            AttributeError: If the protobuf message class does not exist.

        Returns:
            bytes: Serialized protobuf 'Wrapper' message bytes ready for transmission.
        """
        # logging.info(f"Creating message | type: {message_type}, action: {action}, positionals: {args}, explicits: {kwargs.keys()}")
        # If an action is provided, convert it to its corresponding enum value using the factory
        message_action = None
        if action:
            message_action = factory_message_action(message_type, action)

        # Retrieve the template for the provided message type
        message_template = self._message_templates.get(message_type)
        if not message_template:
            raise ValueError(f"Invalid message type '{message_type}'")

        # Extract parameters and defaults from the template
        template_params = message_template["parameters"]
        default_values: dict = message_template.get("defaults", {})

        # Dynamically retrieve the class for the protobuf message (e.g., OfferMessage)
        class_name = message_type.capitalize() + "Message"
        message_class = getattr(nebula_pb2, class_name, None)

        if message_class is None:
            raise AttributeError(f"Message type {message_type} not found on the protocol")

        # Set the 'action' parameter if required and if the message_action is available
        if "action" in template_params and message_action is not None:
            kwargs["action"] = message_action

        # Map positional arguments to template parameters
        remaining_params = [param_name for param_name in template_params if param_name not in kwargs]
        if args:
            for param_name, arg_value in zip(remaining_params, args, strict=False):
                if param_name in kwargs:
                    continue
                kwargs[param_name] = arg_value

        # Fill in missing parameters with their default values
        # logging.info(f"kwargs parameters: {kwargs.keys()}")
        for param_name in template_params:
            if param_name not in kwargs:
                # logging.info(f"Filling parameter '{param_name}' with default value: {default_values.get(param_name)}")
                kwargs[param_name] = default_values.get(param_name)

        # Create an instance of the protobuf message class using the constructed kwargs
        message = message_class(**kwargs)

        message_wrapper = nebula_pb2.Wrapper()
        message_wrapper.source = self.addr
        field_name = f"{message_type}_message"
        getattr(message_wrapper, field_name).CopyFrom(message)
        data = message_wrapper.SerializeToString()
        return data
