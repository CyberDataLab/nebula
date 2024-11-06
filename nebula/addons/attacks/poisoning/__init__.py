"""
Utilities for data poisoning techniques in machine learning. It includes three main components:

1. **Data Poisoning (`datapoisoning.py`)**: Functions to apply various types of noise to training datasets, either randomly or targeted, altering the data to test the model's resilience against corrupted inputs.

2. **Model Poisoning (`modelpoisoning.py`)**: A utility for injecting noise directly into a model's parameters, simulating attacks on model integrity by modifying the underlying weights and biases.

3. **Label Flipping (`labelflipping.py`)**: Functions to randomly change labels within a dataset or target specific labels for modification, effectively simulating label corruption to evaluate the impact on model performance.

Together, these components provide a comprehensive toolkit for researching and implementing poisoning attacks in machine learning systems, aiding in the development of more robust models.
"""
