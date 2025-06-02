import asyncio
import logging
from functools import wraps

from nebula.addons.attacks.communications.communicationattack import CommunicationAttack
from nebula.core.network.communications import CommunicationsManager


class DelayerAttack(CommunicationAttack):
    """
    Implements an attack that delays the execution of a target method by a specified amount of time.
    """

    def __init__(self, engine, attack_params: dict):
        """
        Initializes the DelayerAttack with the engine and attack parameters.

        Args:
            engine: The engine managing the attack context.
            attack_params (dict): Parameters for the attack, including the delay duration.
        """
        try:
            self.delay = int(attack_params["delay"])
            round_start = int(attack_params["round_start_attack"])
            round_stop = int(attack_params["round_stop_attack"])
            attack_interval = int(attack_params["attack_interval"])
            self.target_percentage = int(attack_params["target_percentage"])
            self.selection_interval = int(attack_params["selection_interval"])
        except KeyError as e:
            raise ValueError(f"Missing required attack parameter: {e}")
        except ValueError:
            raise ValueError("Invalid value in attack_params. Ensure all values are integers.")

        super().__init__(
            engine,
            CommunicationsManager.get_instance(),
            "send_message",
            round_start,
            round_stop,
            attack_interval,
            self.delay,
            self.target_percentage,
            self.selection_interval,
        )

    def decorator(self, delay: int):
            """
            Decorator that adds a delay to the execution of the original method.

            Args:
                delay (int): The time in seconds to delay the method execution.

            Returns:
                function: A decorator function that wraps the target method with the delay logic.
            """

            def decorator(func):
                @wraps(func)
                async def wrapper(*args, **kwargs):
                    if len(args) == 4 and args[3] == "model":
                        dest_addr = args[1]
                        if dest_addr in self.targets:
                            logging.info(f"[DelayerAttack] Delaying model propagation to {dest_addr} by {delay} seconds")
                            await asyncio.sleep(delay)
                    _, *new_args = args  # Exclude self argument
                    return await func(*new_args)

                return wrapper

            return decorator
