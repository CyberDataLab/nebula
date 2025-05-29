import importlib
import logging
from abc import ABC, abstractmethod

# To take into account:
# - Malicious nodes do not train on their own data
# - Malicious nodes aggregate the weights of the other nodes, but not their own
# - The received weights may be the node own weights (aggregated of neighbors), or
#   if the attack is performed specifically for one of the neighbors, it can take
#   its weights only (should be more effective if they are different).


class AttackException(Exception):
    pass


class Attack(ABC):
    """
    Base class for implementing various attack behaviors by dynamically injecting
    malicious behavior into existing functions or methods.

    This class provides an interface for replacing benign functions with malicious
    behaviors and for defining specific attack implementations. Subclasses must
    implement the `attack` and `_inject_malicious_behaviour` methods.
    """

    async def _replace_benign_function(function_route: str, malicious_behaviour):
        """
        Dynamically replace a method in a class with a malicious behavior.

        Args:
            function_route (str): The route to the class and method to be replaced, in the format 'module.class.method'.
            malicious_behaviour (callable): The malicious function that will replace the target method.

        Raises:
            AttributeError: If the specified class does not have the target method.
            ImportError: If the module specified in `function_route` cannot be imported.
            Exception: If any other error occurs during the process.

        Returns:
            None
        """
        try:
            *module_route, class_and_func = function_route.rsplit(".", maxsplit=1)
            module = ".".join(module_route)
            class_name, function_name = class_and_func.split(".")

            # Import the module
            module_obj = importlib.import_module(module)

            # Retrieve the class
            changing_class = getattr(module_obj, class_name)

            # Verify the class has the target method
            if not hasattr(changing_class, function_name):
                raise AttributeError(f"Class '{class_name}' has no method named: '{function_name}'.")

            # Replace the original method with the malicious behavior
            setattr(changing_class, function_name, malicious_behaviour)
            print(f"Function '{function_name}' has been replaced with '{malicious_behaviour.__name__}'.")
        except Exception as e:
            logging.exception(f"Error replacing function: {e}")

    @abstractmethod
    async def attack(self):
        """
        Abstract method to define the attack logic.

        Subclasses must implement this method to specify the actions to perform
        during an attack.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError

    @abstractmethod
    async def _inject_malicious_behaviour(self, target_function: callable, *args, **kwargs) -> None:
        """
        Abstract method to inject a malicious behavior into an existing function.

        This method must be implemented in subclasses to define how the malicious
        behavior should interact with the target function.

        Args:
            target_function (callable): The function to inject the malicious behavior into.
            *args: Positional arguments for the malicious behavior.
            **kwargs: Keyword arguments for the malicious behavior.

        Raises:
            NotImplementedError: If the method is not implemented in a subclass.
        """
        raise NotImplementedError


def create_attack(engine) -> Attack:
    """
    Creates an attack object based on the attack name specified in the engine configuration.

    This function uses a predefined map of available attacks (`ATTACK_MAP`) to instantiate
    the corresponding attack class based on the attack name in the configuration. The attack
    parameters are also extracted from the configuration and passed when creating the attack object.

    Args:
        engine (object): The training engine object containing the configuration for the attack.

    Returns:
        Attack: An instance of the specified attack class.

    Raises:
        AttackException: If the specified attack name is not found in the `ATTACK_MAP`.
    """
    from nebula.addons.attacks.communications.delayerattack import DelayerAttack
    from nebula.addons.attacks.communications.floodingattack import FloodingAttack
    from nebula.addons.attacks.dataset.datapoison import SamplePoisoningAttack
    from nebula.addons.attacks.dataset.labelflipping import LabelFlippingAttack
    from nebula.addons.attacks.model.gllneuroninversion import GLLNeuronInversionAttack
    from nebula.addons.attacks.model.modelpoison import ModelPoisonAttack
    from nebula.addons.attacks.model.swappingweights import SwappingWeightsAttack

    ATTACK_MAP = {
        "GLL Neuron Inversion": GLLNeuronInversionAttack,
        "Swapping Weights": SwappingWeightsAttack,
        "Delayer": DelayerAttack,
        "Flooding": FloodingAttack,
        "Label Flipping": LabelFlippingAttack,
        "Sample Poisoning": SamplePoisoningAttack,
        "Model Poisoning": ModelPoisonAttack,
    }

    # Get attack name and parameters from the engine configuration
    attack_params = engine.config.participant["adversarial_args"].get("attack_params", {})
    attack_name = attack_params.get("attacks", None)
    if attack_name is None:
        raise AttackException("No attack specified")

    # Look up the attack class based on the attack name
    attack = ATTACK_MAP.get(attack_name)

    # If the attack is found, return an instance of the attack class
    if attack:
        return attack(engine, dict(attack_params))
    else:
        # If the attack name is not found, raise an exception
        raise AttackException(f"Attack {attack_name} not found")
