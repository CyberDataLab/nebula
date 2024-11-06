from torch.utils.data import Subset

from nebula.addons.attacks.poisoning.datapoison import datapoison
from nebula.addons.attacks.poisoning.labelflipping import labelFlipping


class ChangeableSubset(Subset):
    def __init__(
        self,
        dataset,
        indices,
        label_flipping=False,
        data_poisoning=False,
        poisoned_percent=0,
        poisoned_ratio=0,
        targeted=False,
        target_label=0,
        target_changed_label=0,
        noise_type="salt",
    ):
        super().__init__(dataset, indices)
        new_dataset = dataset
        self.dataset = new_dataset
        self.indices = indices
        self.label_flipping = label_flipping
        self.data_poisoning = data_poisoning
        self.poisoned_percent = poisoned_percent
        self.poisoned_ratio = poisoned_ratio
        self.targeted = targeted
        self.target_label = target_label
        self.target_changed_label = target_changed_label
        self.noise_type = noise_type

        if self.label_flipping:
            self.dataset = labelFlipping(
                self.dataset,
                self.indices,
                self.poisoned_percent,
                self.targeted,
                self.target_label,
                self.target_changed_label,
            )
        if self.data_poisoning:
            self.dataset = datapoison(
                self.dataset,
                self.indices,
                self.poisoned_percent,
                self.poisoned_ratio,
                self.targeted,
                self.target_label,
                self.noise_type,
            )

    def __getitem__(self, idx):
        if isinstance(idx, list):
            return self.dataset[[self.indices[i] for i in idx]]
        return self.dataset[self.indices[idx]]

    def __len__(self):
        return len(self.indices)
