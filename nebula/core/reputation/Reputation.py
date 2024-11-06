import os
import csv
import logging
import json
import time
import numpy as np
from datetime import datetime, timedelta
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from nebula.core.engine import Engine

def save_data(scenario, type_data, source_ip, addr, round=None, time=None, data_contribution=None, type_message=None, current_round=None, fraction_changed=None, total_params=None, changed_params=None, threshold=None, changes_record=None, rate_of_change=None):
    """
    Save communication data between nodes and aggregated models.

    Args:
        source_ip (str): Source IP address.
        addr (str): Destination IP address.
        round (int): Round number.
        time (float): Time taken to process the data. 
    """

    source_ip = source_ip.split(":")[0]
    addr = addr.split(":")[0]

    try:
        combined_data = {}

        if type_data == 'communication':
            combined_data["communication"] = {
                "time": time,
                "current_round": current_round,
                "round": round,
                "type_message": type_message,
            }
        elif type_data == 'time_message':
            combined_data["time_message"] = {
                "time": time,
                "type_message": type_message,
                "round": round,
                "current_round": current_round,
            }
        elif type_data == 'fraction_of_params_changed':
            combined_data["fraction_of_params_changed"] = {
                "total_params": total_params,
                "changed_params": changed_params,
                "fraction_changed": fraction_changed,
                "threshold": threshold,
                "changes_record": changes_record,
                "round": round,
            }

        script_dir = os.path.dirname(os.path.abspath(__file__))
        file_name = f"{addr}_storing_{source_ip}_info.json"
        full_file_path = os.path.join(script_dir, scenario, file_name)
        os.makedirs(os.path.dirname(full_file_path), exist_ok=True)

        all_metrics = []
        if os.path.exists(full_file_path):
            with open(full_file_path, 'r') as existing_file:
                try:
                    all_metrics = json.load(existing_file)
                except json.JSONDecodeError:
                    logging.error(f"JSON decode error in file: {full_file_path}")
                    all_metrics = []

        all_metrics.append(combined_data)

        with open(full_file_path, 'w') as json_file:
                json.dump(all_metrics, json_file, indent=4)

    except Exception as e:
        logging.error(f"Error saving data: {e}")

class Reputation:
    """
    Class to define the reputation of a participant.
    """
    reputation_history = {}
    communication_history = {}
    frequency_history = {}
    neighbor_reputation_history = {}
    fraction_changed_history = {}
    communication_data = []
    messages_frequency = []
    previous_threshold_freq = {}
    mean_time_communication = None
    communication_score = 0.0
    
    def __init__(self, engine: "Engine"):
        self._engine = engine

    @property
    def engine(self):
        return self._engine

    def calculate_reputation(self, scenario, log_dir, id_node, addr, nei, current_round=None):
        """
        Calculate the reputation of each participant based on the data stored.

        Args:
            scenario (str): Scenario name.
        """
        logging.info(f"id_node: {id_node}, addr: {addr}, nei: {nei}")
        addr = addr.split(":")[0].strip()
        nei = nei.split(":")[0].strip()

        # array_communication = []
        # array_messages_frequency = []
        communication_time_normalized = 0
        messages_frequency_normalized = 0
        messages_frequency_count = 0
        avg_communication_time_normalized = 0
        avg_messages_frequency_normalized = 0
        fraction_score = 0
        fraction_score_asign = 0

        try:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            file_name = f"{addr}_storing_{nei}_info.json" # Read the file to calculate the reputation
            full_file_path = os.path.join(script_dir, scenario, file_name)
            os.makedirs(os.path.dirname(full_file_path), exist_ok=True)

            if os.path.exists(full_file_path) and os.path.getsize(full_file_path) > 0:
                with open(full_file_path, 'r') as json_file:
                    all_metrics = json.load(json_file)
                    for metric in all_metrics:
                        if "communication" in metric:
                            type_message = metric["communication"]["type_message"]
                            round = metric["communication"]["round"] 
                            current_round_comm = metric["communication"]["current_round"]
                            time = metric["communication"]["time"]
                            if current_round == current_round_comm:
                                communication_time_normalized = Reputation.manage_metric_communication(type_message, round, current_round_comm, time, addr , nei)
                        if "time_message" in metric:
                            round = metric["time_message"]["round"]
                            current_round_mess = metric["time_message"]["current_round"]
                            time = metric["time_message"]["time"]
                            type_message = metric["time_message"]["type_message"]
                            if current_round == current_round_mess:
                                Reputation.messages_frequency.append({"time_message": time, "type_message": type_message, "round": round, "current_round": current_round, "key": (addr, nei)})
                        if "fraction_of_params_changed" in metric:
                            round = metric["fraction_of_params_changed"]["round"]
                            total_params = metric["fraction_of_params_changed"]["total_params"]
                            changed_params = metric["fraction_of_params_changed"]["changed_params"]
                            fraction_changed = metric["fraction_of_params_changed"]["fraction_changed"]
                            threshold = metric["fraction_of_params_changed"]["threshold"]
                            changes_record = metric["fraction_of_params_changed"]["changes_record"]
                            if round == current_round:
                                Reputation.analyze_anomalies(addr, nei, round, current_round, fraction_changed, threshold, changes_record, changed_params, total_params)
                                #logging.info(f"Reputation.fraction_changed_history: {Reputation.fraction_changed_history}")

                    similarity_file = os.path.join(log_dir, f"participant_{id_node}_similarity.csv")
                    similarity_reputation = Reputation.read_similarity_file(similarity_file, nei)
                    #logging.info(f"Similarity reputation: {similarity_reputation}")

                    if communication_time_normalized is not None:
                        avg_communication_time_normalized = Reputation.save_communication_history(addr, nei, communication_time_normalized, current_round)
                        if avg_communication_time_normalized is None and current_round >= 5:
                            avg_communication_time_normalized = Reputation.communication_history[(addr, nei)][current_round - 1]["avg_communication"]
                            logging.info(f"Avg communication is None and current_round = {current_round}, avg_communication_time_normalized: {avg_communication_time_normalized}")

                    if Reputation.messages_frequency is not None:
                        messages_frequency_normalized, messages_frequency_count = Reputation.manage_metric_frequency(Reputation.messages_frequency, addr, nei, current_round)
                        avg_messages_frequency_normalized = Reputation.save_frequency_history(addr, nei, messages_frequency_normalized, current_round)
                        if avg_messages_frequency_normalized is None and current_round >= 4:
                            avg_messages_frequency_normalized = Reputation.frequency_history[(addr, nei)][current_round - 1]["avg_frequency"] 
                            logging.info(f"Avg messages frequency is None and curret_round = {current_round}, avg_messages_frequency_normalized: {avg_messages_frequency_normalized}")

                    if Reputation.fraction_changed_history is not None:
                        key = (addr, nei, current_round)
                        if key not in Reputation.fraction_changed_history:
                            key = (addr, nei, current_round - 1) if current_round > 0 else None 
                            logging.info(f"Key prev: {key}")
                        fraction_score = Reputation.fraction_changed_history[key].get("fraction_score")
                        logging.info(f"Fraction score: {fraction_score} | key: {key}")
                        fraction_score_asign = fraction_score if fraction_score is not None else 0
                        logging.info(f"Fraction score asign: {fraction_score_asign}")
        
                    # Weights for each metric
                    if current_round is not None:
                        if current_round >= 4:
                            weight_to_similarity = 0.5
                            weight_to_communication = 0.0
                            weight_to_fraction = 0.0
                            weight_to_message_frequency = 0.5
                        elif current_round >= 5:
                            weight_to_similarity = 0.3
                            weight_to_communication = 0.3
                            weight_to_fraction = 0.2
                            weight_to_message_frequency = 0.2
                        else:
                            weight_to_similarity = 1.0
                            weight_to_communication = 0.0
                            weight_to_fraction = 0.0
                            weight_to_message_frequency = 0.0
                    
                    # Reputation calculation
                    reputation = ( weight_to_communication * avg_communication_time_normalized 
                                + weight_to_message_frequency * avg_messages_frequency_normalized
                                + weight_to_similarity * similarity_reputation
                                + weight_to_fraction * fraction_score_asign)	

                    # Create graphics to metrics
                    self.create_graphics_to_metrics(avg_communication_time_normalized, messages_frequency_count, avg_messages_frequency_normalized, similarity_reputation, fraction_score_asign, addr, nei, current_round, self.engine.total_rounds)

                    # Save history reputation
                    average_reputation = Reputation.save_reputation_history_in_memory(addr, nei, reputation, current_round)
                    
                    logging.info(f"Average reputation to node {nei}: {average_reputation}")
                    return average_reputation
        except Exception as e:
            logging.error(f"Error calculating reputation: {e}, type: {type(e).__name__}")

    def create_graphics_to_metrics(self, com_time, mess_fre_count, mess_fre_norm, similarity, fraction, addr, nei, current_round, total_rounds):
        """
        Create graphics to metrics.
        """
        
        if current_round is not None and current_round < total_rounds:
            communication_time_dict = {
                f"Reputation_communication_time/{addr}": {
                    nei: com_time
                }
            }

            messages_frequency_count_dict = {
                f"Reputation_messages_frequency_count/{addr}": {
                    nei: mess_fre_count
                }
            }

            messages_frequency_norm_dict = {
                f"Reputation_messages_frequency_normalized/{addr}": {
                    nei: mess_fre_norm
                }
            }

            similarity_dict = {
                f"Reputation_similarity/{addr}": {
                    nei: similarity
                }
            }

            fraction_dict = {
                f"Reputation_fraction/{addr}": {
                    nei: fraction
                }
            }
            
            if communication_time_dict is not None:
                self.engine.trainer._logger.log_data(communication_time_dict, step=current_round)

            if messages_frequency_count_dict is not None:
                self.engine.trainer._logger.log_data(messages_frequency_count_dict, step=current_round)

            if messages_frequency_norm_dict is not None:
                self.engine.trainer._logger.log_data(messages_frequency_norm_dict, step=current_round)

            if similarity_dict is not None:
                self.engine.trainer._logger.log_data(similarity_dict, step=current_round)

            if fraction_dict is not None:
                self.engine.trainer._logger.log_data(fraction_dict, step=current_round)

    @staticmethod
    def analyze_anomalies(addr, nei, round_num, current_round, fraction_changed, threshold, changes_record, changed_params, total_params):
        """
        Analyze anomalies in the fraction of parameters changed.
        """
        try:
            key = (addr, nei, round_num)

            if key not in Reputation.fraction_changed_history:
                prev_key = (addr, nei, round_num - 1)
                if round_num > 0 and prev_key in Reputation.fraction_changed_history:
                    previous_data = Reputation.fraction_changed_history[prev_key]
                    fraction_changed = fraction_changed if fraction_changed is not None else previous_data["fraction_changed"]
                    threshold = threshold if threshold is not None else previous_data["threshold"]
                else:
                    fraction_changed = fraction_changed if fraction_changed is not None else 0
                    threshold = threshold if threshold is not None else 0

                Reputation.fraction_changed_history[key] = {
                    "fraction_changed": fraction_changed,
                    "threshold": threshold,
                    "fraction_score": None,
                    "fraction_anomaly": False,
                    "threshold_anomaly": False,
                    "mean_fraction": None,
                    "std_dev_fraction": None,
                    "mean_threshold": None,
                    "std_dev_threshold": None,
                }

            # Calcular y almacenar estadísticas solo hasta la ronda 4
            if round_num < 5:
                past_fractions = []
                past_thresholds = []

                for r in range(round_num):
                    past_key = (addr, nei, r)
                    if past_key in Reputation.fraction_changed_history:
                        past_fractions.append(Reputation.fraction_changed_history[past_key]["fraction_changed"])
                        past_thresholds.append(Reputation.fraction_changed_history[past_key]["threshold"])

                if past_fractions:
                    mean_fraction = np.mean(past_fractions)
                    std_dev_fraction = np.std(past_fractions)
                    Reputation.fraction_changed_history[key]["mean_fraction"] = mean_fraction
                    Reputation.fraction_changed_history[key]["std_dev_fraction"] = std_dev_fraction

                if past_thresholds:
                    mean_threshold = np.mean(past_thresholds)
                    std_dev_threshold = np.std(past_thresholds)
                    Reputation.fraction_changed_history[key]["mean_threshold"] = mean_threshold
                    Reputation.fraction_changed_history[key]["std_dev_threshold"] = std_dev_threshold

            else: 
                fraction_value = 0
                threshold_value = 0
                prev_key = (addr, nei, round_num - 1)
                if prev_key not in Reputation.fraction_changed_history:
                    prev_key = (addr, nei, round_num - 2)
            
                mean_fraction_prev = Reputation.fraction_changed_history[prev_key]["mean_fraction"]
                std_dev_fraction_prev = Reputation.fraction_changed_history[prev_key]["std_dev_fraction"]
                mean_threshold_prev = Reputation.fraction_changed_history[prev_key]["mean_threshold"]
                std_dev_threshold_prev = Reputation.fraction_changed_history[prev_key]["std_dev_threshold"]
                # logging.info(f"Round: {round_num}, Mean fraction: {mean_fraction_prev}, Std dev fraction: {std_dev_fraction_prev}, Mean threshold: {mean_threshold_prev}, Std dev threshold: {std_dev_threshold_prev}")

                current_fraction = Reputation.fraction_changed_history[key]["fraction_changed"]
                current_threshold = Reputation.fraction_changed_history[key]["threshold"]
                # logging.info(f"Round: {round_num}, Current fraction: {current_fraction}, Current threshold: {current_threshold}")

                #low_mean_fraction_prev = mean_fraction_prev - std_dev_fraction_prev
                upper_mean_fraction_prev = mean_fraction_prev + std_dev_fraction_prev
                #low_mean_threshold_prev = mean_threshold_prev - std_dev_threshold_prev
                upper_mean_threshold_prev = mean_threshold_prev + std_dev_threshold_prev

                #fraction_anomaly = not (low_mean_fraction_prev <= current_fraction <= upper_mean_fraction_prev)
                #threshold_anomaly = not (low_mean_threshold_prev <= current_threshold <= upper_mean_threshold_prev)
                fraction_anomaly = current_fraction > upper_mean_fraction_prev
                threshold_anomaly = current_threshold > upper_mean_threshold_prev
                # logging.info(f"Round: {round_num}, Fraction anomaly: {fraction_anomaly}, Threshold anomaly: {threshold_anomaly}")

                Reputation.fraction_changed_history[key]["fraction_anomaly"] = fraction_anomaly
                Reputation.fraction_changed_history[key]["threshold_anomaly"] = threshold_anomaly

                # Calculate the fraction score
                k_fraction = 1 / std_dev_fraction_prev if std_dev_fraction_prev != 0 else 1
                # logging.info(f"Round: {round_num}, K fraction: {k_fraction}")
                k_threshold = 1 / std_dev_threshold_prev if std_dev_threshold_prev != 0 else 1
                # logging.info(f"Round: {round_num}, K threshold: {k_threshold}")
                fraction_value =  1 / (1 + np.exp(-k_fraction * (current_fraction - mean_fraction_prev))) if current_fraction is not None and mean_fraction_prev is not None else 0
                # logging.info(f"Round: {round_num}, Fraction: {fraction_value}")
                threshold_value = 1 / (1 + np.exp(-k_threshold * (current_threshold - mean_threshold_prev))) if current_threshold is not None and mean_threshold_prev is not None else 0
                # logging.info(f"Round: {round_num}, Threshold: {threshold_value}")

                if threshold_anomaly:
                    fraction_weight = 0.8
                    threshold_weight = 0.2
                elif fraction_anomaly:
                    fraction_weight = 0.4
                    threshold_weight = 0.6
                else:
                    fraction_weight = 0.5
                    threshold_weight = 0.5

                fraction_score = 1 - (fraction_weight * fraction_value + threshold_weight * threshold_value)
                Reputation.fraction_changed_history[key]["fraction_score"] = fraction_score

                # Upload the values to the history
                Reputation.fraction_changed_history[key]["mean_fraction"] = (current_fraction + mean_fraction_prev) / 2
                Reputation.fraction_changed_history[key]["std_dev_fraction"] = np.sqrt(((current_fraction - mean_fraction_prev) ** 2 + std_dev_fraction_prev ** 2) / 2)
                Reputation.fraction_changed_history[key]["mean_threshold"] = (current_threshold + mean_threshold_prev) / 2
                Reputation.fraction_changed_history[key]["std_dev_threshold"] = np.sqrt(((0.1 * (current_threshold - mean_threshold_prev) ** 2) + std_dev_threshold_prev ** 2) / 2)

                # Score not negative
                Reputation.fraction_changed_history[key]["fraction_score"] = max(fraction_score, 0)
        except Exception as e:
            logging.error(f"Error analyzing anomalies: {e}")

    @staticmethod
    def save_frequency_history(addr, nei, messages_frequency_normalized, current_round):
        """
        Save the frequency history of a participant (addr) regarding its neighbor (nei) in memory.

        Args:
            addr (str): The identifier of the node whose frequency history is being saved.
            nei (str): The neighboring node involved.
            messages_frequency_normalized (float): The frequency value to be saved.
            current_round (int): The current round number.

        Returns:
            float: The cumulative frequency including the current round.
        """

        try:
            key = (addr, nei)

            if key not in Reputation.frequency_history:
                Reputation.frequency_history[key] = {}

            Reputation.frequency_history[key][current_round] = {
                "frequency": messages_frequency_normalized
            }

            # logging.info(f"Frequency: {messages_frequency_normalized}")
            # logging.info(f"Frequency history: {Reputation.frequency_history}")

            rounds = Reputation.frequency_history[key]
            if messages_frequency_normalized != 0 and current_round > 3:
                previous_avg = Reputation.frequency_history[key].get(current_round - 1, {}).get("avg_frequency", None)
                # logging.info(f"Previous avg frequency: {previous_avg}")
                if previous_avg is not None:
                    avg_frequency = (messages_frequency_normalized + previous_avg) / 2
                else:
                    avg_frequency = messages_frequency_normalized
                
                Reputation.frequency_history[key][current_round]["avg_frequency"] = avg_frequency
            else:
                avg_frequency = 0

            # logging.info(f"Avg frequency: {avg_frequency}")
            return avg_frequency
        except Exception as e:
            logging.error(f"Error saving frequency history: {e}")

    @staticmethod
    def manage_metric_frequency(messages_frequency, addr, nei, current_round):
        try:
            # start_time = time.time()
            # interval = 60
            current_addr_nei = (addr, nei)            
            threshold = 0
            previous_threshold = Reputation.previous_threshold_freq.get(current_addr_nei, 0)
            relevant_messages = [msg for msg in messages_frequency if msg["key"] == current_addr_nei and msg["current_round"] == current_round]
            messages_count = len(relevant_messages) if relevant_messages else 0
            # logging.info(f"Round {current_round}. Relevant messages: {relevant_messages}, Messages count: {messages_count}")

            if current_round >= 0 and current_round <= 2:
                previous_counts = [
                    len([m for m in messages_frequency if m["key"] == current_addr_nei and m["current_round"] == r])
                    for r in range(3)
                ]
                threshold = np.mean(previous_counts) if previous_counts else 0
                Reputation.previous_threshold_freq[current_addr_nei] = threshold
                # logging.info(f"Round {current_round}. Previous counts: {previous_counts}, Threshold: {threshold}")
                normalized_messages = 0.0
            elif current_round >= 3:
                threshold = previous_threshold
                # logging.info(f"Round {current_round}. Prev threshold: {threshold}")

                if messages_count > threshold:
                    excess = messages_count - threshold
                    normalized_messages = 1 - (excess / messages_count) if messages_count > 0 else 0
                    # logging.info(f"Round {current_round}. Excess: {excess}, Normalized messages: {normalized_messages}")
                else:
                    normalized_messages = 1 - ((threshold - messages_count) / (threshold + messages_count)) if threshold > 0 else 0
                    # logging.info(f"Round {current_round}. Normalized messages: {normalized_messages}")

                if previous_threshold > 0:
                    threshold = (messages_count + previous_threshold) / 2
                Reputation.previous_threshold_freq[current_addr_nei] = threshold
                # logging.info(f"Round {current_round}. New threshold: {threshold}")
            else:
                normalized_messages = 0.0
            
            return normalized_messages, messages_count
        except Exception as e:
            logging.error(f"Error managing frequency metric: {e}")
            return 0.0, 0
    
    @staticmethod
    def manage_metric_communication(type_message, round, current_round, time, addr, nei):
        """
        Manage the communication metric.

        Args:
            type_message (str): Type of message.
            round (int): Round number.
            current_round (int): Current round number.
            time (float): Time taken to process the data.
            addr (str): Source IP address.
            nei (str): Destination IP address.

        Returns:
            float: Normalized communication value.
        """
        try:
            Reputation.communication_data.append({
                "time": time, 
                "type_message": type_message, 
                "round": round, 
                "current_round": current_round,
                "key": (addr, nei)
            })

            #logging.info(f"Communication data: {Reputation.communication_data}")

            current_addr_nei = (addr, nei)
            filtered_communications = [comm for comm in Reputation.communication_data if comm["key"] == current_addr_nei]
            #logging.info(f"Round {current_round}. Filtered by key: {filtered_communications}")

            if current_round == 5: 
                model_times = [comm["time"] for comm in filtered_communications if comm["type_message"] == "model" and comm["current_round"] < 5]
                #logging.info(f"Round {current_round}. Model times: {model_times}")

                if model_times:
                    Reputation.mean_time_communication = np.mean(model_times)
                    #logging.info(f"Round {current_round}. Mean time communication: {Reputation.mean_time_communication}")

                    difference = abs(time - Reputation.mean_time_communication)
                    #logging.info(f"Round {current_round}. Time: {time} difference: {difference}")

                    penalty_range = difference / Reputation.mean_time_communication
                    #logging.info(f"Round {current_round}. Penalty range: {penalty_range}")

                    if time < Reputation.mean_time_communication:
                        reduction_factor = 1 - (difference / Reputation.mean_time_communication)
                        penalty_range *= reduction_factor
                        #logging.info(f"Round {current_round}. Normal penalty reduction: {penalty_range}")

                    if round != current_round:
                        round_difference = abs(current_round - round)
                        penalty_range += round_difference * 0.1
                        #logging.info(f"Round {round} != current round {current_round}.  Additional penalty for round difference.")

                    Reputation.communication_score = max(0, 1 - penalty_range)
                    #logging.info(f"Round {current_round}. Communication score: {Reputation.communication_score}")
                else:
                    Reputation.communication_score = 0.0
                    Reputation.mean_time_communication = 0.0
                    #logging.info(f"Round {current_round}. No data to calculate communication score")

                return Reputation.communication_score

            elif current_round > 5 and Reputation.mean_time_communication is not None:
                previous_mean = Reputation.mean_time_communication
                Reputation.mean_time_communication = (previous_mean  + time) / 2
                #logging.info(f"Round {current_round}. Update mean time communication: {Reputation.mean_time_communication}")

                difference = abs(time - Reputation.mean_time_communication)
                #logging.info(f"Round {current_round}. Time: {time} difference: {difference}")

                # max_time = max(comm["time"] for comm in Reputation.communication_data if comm["type_message"] == "model" and comm["key"] == (addr, nei))
                # logging.info(f"Round {current_round}. Max time for score calculation: {max_time}")

                penalty_range = difference / Reputation.mean_time_communication
                #logging.info(f"Round {current_round}. Penalty range: {penalty_range}")

                if time < Reputation.mean_time_communication:
                    reduction_factor = 1 - (difference / Reputation.mean_time_communication)
                    penalty_range *= reduction_factor
                    #logging.info(f"Round {current_round}. Normal penalty reduction: {penalty_range}")

                if round != current_round:
                    round_difference = abs(current_round - round)
                    penalty_range += round_difference * 0.1
                    #logging.info(f"Round {round} != current round {current_round}.  Additional penalty for round difference.")

                penalty_range = min(penalty_range, 1)
                #logging.info(f"Round {current_round}. Penalty range: {penalty_range}")

                Reputation.communication_score = max(0, 1 - penalty_range)
                #logging.info(f"Round {current_round}. Communication score: {Reputation.communication_score}")
            else:
                Reputation.communication_score = 0.0

            return Reputation.communication_score             

        except Exception as e:
            logging.error(f"Error managing communication metric: {e}")

    @staticmethod
    def save_communication_history(addr, nei, communication, current_round):
        """
        Save the communication history of a participant (addr) regarding its neighbor (nei) in memory.

        Args:
            addr (str): The identifier of the node whose communication history is being saved.
            nei (str): The neighboring node involved.
            communication (float): The communication value to be saved.
            current_round (int): The current round number.

        Returns:
            float: The cumulative communication including the current round.
        """
        try:
            key = (addr, nei)

            if key not in Reputation.communication_history:
                Reputation.communication_history[key] = {}

            Reputation.communication_history[key][current_round] = {
                "communication": communication
            }

            # logging.info(f"Communication: {communication}")
            # logging.info(f"Communication history: {Reputation.communication_history}")

            rounds = Reputation.communication_history[key]
            #recent_rounds = sorted(rounds.keys(), reverse=True) #[:2]
            if communication != 0 and current_round > 4:
                previous_avg = Reputation.communication_history[key].get(current_round - 1, {}).get("avg_communication", None)
                # logging.info(f"Previous avg communication: {previous_avg}")

                if previous_avg is not None:
                    avg_communication = (communication + previous_avg) / 2
                else:
                    avg_communication = communication
                
                Reputation.communication_history[key][current_round]["avg_communication"] = avg_communication
            else:
                avg_communication = 0

            # logging.info(f"Avg communication: {avg_communication}")
            return avg_communication
        except Exception as e:
            logging.error(f"Error saving communication history: {e}")

    @staticmethod
    def save_reputation_history_in_memory(addr, nei, reputation, current_round):
        """
        Save the reputation history of a participant (addr) regarding its neighbor (nei) in memory 
        and calculate the average reputation.

        Args:
            addr (str): The identifier of the node whose reputation is being saved.
            nei (str): The neighboring node involved.
            reputation (float): The reputation value to be saved.
            current_round (int): The current round number.

        Returns:
            float: The cumulative reputation including the current round.
        """
        try:
            key = (addr, nei) 

            if key not in Reputation.reputation_history:
                Reputation.reputation_history[key] = {}

            Reputation.reputation_history[key][current_round] = reputation

            total_reputation = 0
            total_weights = 0
            rounds = sorted(Reputation.reputation_history[key].keys(), reverse=True)[:3]

            for i, round in enumerate(rounds, start=1):
                rep = Reputation.reputation_history[key][round]
                decay_factor = Reputation.calculate_decay_rate(rep) ** (i * 2) # Aument the decay factor * 2
                total_reputation += rep * decay_factor
                total_weights += decay_factor
                # logging.info(f"Round: {round}, Reputation: {rep}, Decay: {decay_factor}, Total reputation: {total_reputation}")

            if total_weights > 0:
                avg_reputation = total_reputation / total_weights
            else:
                avg_reputation = 0

            return avg_reputation
        except Exception as e:
            logging.error(f"Error saving reputation history: {e}")
    
    @staticmethod
    def calculate_decay_rate(reputation):
        """
        Calculate the decay rate for a reputation value.

        Args:
            reputation (float): Reputation value.

        Returns:
            float: Decay rate.
        """

        if reputation > 0.8:
            return 0.9 # Muy bajo decaimiento
        elif reputation > 0.6:
            return 0.7  # Bajo decaimiento
        elif reputation > 0.4:
            return 0.5  # Moderado decaimiento
        else:
            return 0.2  # Alto decaimiento
        
    @staticmethod
    def read_similarity_file(file_path, nei):
        """
        Read a similarity file and extract relevant data for each IP.

        Args:
            file_path (str): Path to the similarity file.

        Returns:
            dict: A dictionary containing relevant data for each IP extracted from the file.
                Each IP will have a dictionary containing cosine, euclidean, minkowski,
                manhattan, pearson_correlation, and jaccard values.
        """
        nei = nei.split(":")[0].strip()
        similarity = 0.0
        with open(file_path, 'r') as file:
            reader = csv.DictReader(file)
            for row in reader:
                source_ip = row['source_ip'].split(":")[0].strip()
                if source_ip == nei:
                    try: 
                        # Design weights for each similarity metric
                        weight_cosine = 0.4
                        weight_euclidean = 0.2
                        weight_manhattan = 0.2
                        weight_pearson = 0.2

                        # Retrieve and normalize metrics if necessary
                        cosine = float(row['cosine'])
                        euclidean = float(row['euclidean'])
                        manhattan = float(row['manhattan'])
                        pearson_correlation = float(row['pearson_correlation'])

                        # Calculate similarity
                        similarity = ( weight_cosine * cosine
                                     + weight_euclidean * euclidean
                                     + weight_manhattan * manhattan
                                     + weight_pearson * pearson_correlation)
                    except Exception as e:
                        logging.error(f"Error reading similarity file: {e}")
        return similarity

    @staticmethod
    def callback_normalized_value(array, metric=None, key=None):
        """
        Calculate the reputation of a node based on the normalized values.

        Args:
            array (list): List of values to normalize.
        
        Returns:
            float: Reputation value (or None if array is empty).
        """

        if not array:
            return None
    
        if len(array) == 1:
            if array[0] >= 1:
                return Reputation.normalize(array[0], 0.25, array[0]+1)
            else:
                return Reputation.normalize(array[0], 0.25, array[0])
        
        min_value = min(array)
        max_value = max(array)
        
        # See values from array
        normalized_values = [Reputation.normalize(value, min_value, max_value) for value in array]
        reputation_normalized = sum(normalized_values) / len(normalized_values)

        return reputation_normalized
    
    @staticmethod
    def normalize(value, min_value, max_value):
        """
        Normalize value within a given range.

        Args:
            value (float): Reputation value.
            min_reputation (float): Minimum reputation value.
            max_reputation (float): Maximum reputation value.

        Returns:
            float: Normalized reputation value within the range [1, 10].
        """

        if max_value == min_value:
            return 0.25
        
        normalized_value = (value - min_value) / (max_value - min_value)

        return max(0.0, min(1.0, normalized_value))
    
    # @staticmethod
    # def manage_metric_fraction_of_params_changed(round, total_params, changed_params, changes_record, nei):
    #     if nei not in Reputation.fraction_parameters_changed:
    #         logging.info(f"Creating new entry for neighbor: {nei}")
    #         Reputation.fraction_parameters_changed[nei] = {}

    #     if round not in Reputation.fraction_parameters_changed[nei]:
    #         logging.info(f"Creating new entry for round: {round}")
    #         Reputation.fraction_parameters_changed[nei][round] = {}

    #     fraction_changed = changed_params / total_params if total_params > 0 else 0.0
    #     logging.info(f"Calculating fraction of parameters changed for neighbor: {nei}, round: {round}, fraction_changed: {fraction_changed}")

    #     normalized_fraction = None
    #     threshold = None

    #     if round == 3:
    #         previous_fractions = [
    #             Reputation.fraction_parameters_changed[nei][i]["fraction_changed"]
    #             for i in range(3) if i in Reputation.fraction_parameters_changed[nei]
    #         ]
    #         logging.info(f"Round 3: Previous fractions: {previous_fractions}")

    #         if previous_fractions:
    #             threshold = sum(previous_fractions) / len(previous_fractions)
    #             logging.info(f"Round 3: Calculated threshold: {threshold}, fraction_changed: {fraction_changed}, normalized_fraction: {normalized_fraction}")

    #     elif round > 3:
    #         previous_threshold = Reputation.fraction_parameters_changed[nei][round - 1]["threshold"]

    #         if previous_threshold is not None:
    #             logging.info(f"Round: {round}, Previous threshold: {previous_threshold}")
    #             threshold = (previous_threshold + fraction_changed) / 2
    #             logging.info(f"Round: {round}, Calculated threshold: {threshold}")
    #         else:
    #             previous_fractions = [
    #                 Reputation.fraction_parameters_changed[nei][i]["fraction_changed"]
    #                 for i in range(3) if i in Reputation.fraction_parameters_changed[nei]
    #             ]
    #             if previous_fractions:
    #                 threshold = sum(previous_fractions) / len(previous_fractions)
    #                 logging.info(f"Round: {round}, Calculated threshold: {threshold} based on previous fractions")


    #     Reputation.fraction_parameters_changed[nei][round] = {
    #         "total_params": total_params,
    #         "change_params": changed_params,
    #         "changes_record": changes_record,
    #         "threshold": threshold,
    #         "fraction_changed": fraction_changed,
    #     }

    #     logging.info(f"Reputation.fraction_parameters_changed: {Reputation.fraction_parameters_changed}")
        
    #     return threshold

    # METHODS TO BE USED IN THE FUTURE
    
    # @staticmethod
    # def get_existing_reputation(current, nei, round):
        
    #     Get the existing reputation for a node with respect to a specific neighbor for a specific round.

    #     Args:
    #         addr (str): The identifier of the node whose reputation is being retrieved.
    #         nei (str): The identifier of the neighbor.
    #         round (int): Round number.

    #     Returns:
    #         float: Existing reputation score, or None if not found.
        
    #     key = (current, nei, round)
        
    #     # Comprobar si la clave existe en el historial de reputación
    #     if key in Reputation.reputation_history:
    #         logging.info(f"History key: {key}, reputation: {Reputation.reputation_history[key]}")
    #         history_list = Reputation.reputation_history[key]

    #         # Si la estructura es una lista simple, devolvemos el último valor
    #         return history_list[-1] if history_list else None

    #     return None

    # def combine_reputation_with_neighbour(self, current_node, source, node_ip, score, round):
        
    #     Combine the reputation of a node with its neighbour.

    #     Args:
    #         current_node (str): The current node's IP address.
    #         source (str): Source IP address (the node sending the reputation).
    #         node_ip (str): The node being evaluated.
    #         score (float): Reputation score from neighbour.
    #         round (int): Round number.

    #     Returns:
    #         float: Combined reputation score or None if the calculation has already been done for this round.
        

    #     current_node = current_node.split(":")[0].strip()
    #     source = source.split(":")[0].strip()
    #     node_ip = node_ip.split(":")[0].strip()
    #     logging.info(f"Combining reputation - Current node: {current_node}, Source: {source}, Neighbour: {node_ip}, Score: {score}, Round: {round}")

    #     if current_node == node_ip:
    #         logging.info(f"Node {current_node} ignoring score about itself ({node_ip}).")
    #         return None

    #     # Definir la clave con current_node, node_ip y round
    #     key = (current_node, node_ip, round)

    #     # Proceder con el cálculo de reputación si no existe previamente
    #     if key not in Reputation.neighbor_reputation_history:
    #         Reputation.neighbor_reputation_history[key] = []

    #     # Guardar la nueva puntuación enviada por el vecino
    #     Reputation.neighbor_reputation_history[key].append(score)

    #     # Calcular la reputación promedio del vecino
    #     total_reputation = sum(Reputation.neighbor_reputation_history[key])
    #     average_reputation = total_reputation / len(Reputation.neighbor_reputation_history[key])

    #     # Obtener la reputación existente del historial
    #     existing_reputation = Reputation.get_existing_reputation(current_node, node_ip, round)
    #     if existing_reputation is None:
    #         logging.warning(f"No existing reputation found for node {current_node} with neighbor {node_ip} in round {round}.")
    #         return None

    #     # Definir los pesos para combinar reputaciones
    #     weight_existing = 0.5
    #     weight_new = 0.5

    #     # Combinar la reputación existente con la nueva reputación del vecino
    #     combined_reputation = (weight_existing * existing_reputation) + (weight_new * average_reputation)
    #     logging.info(f"Combined reputation for node {current_node} with neighbor {source}: {combined_reputation}")

    #     return combined_reputation