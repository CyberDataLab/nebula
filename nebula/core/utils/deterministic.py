import logging
import os
import random

import numpy as np
import torch


def enable_deterministic(config):
    seed = config.participant["scenario_args"]["random_seed"]
    logging.info(f"Fixing randomness with seed {seed}")
    np.random.seed(seed)
    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    torch.manual_seed(seed)
    torch.cuda.manual_seed(seed)
    torch.cuda.manual_seed_all(seed)
    torch.backends.cudnn.deterministic = True
    torch.backends.cudnn.benchmark = False
