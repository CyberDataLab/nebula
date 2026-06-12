IMAGE_DATASET_NORMALIZATION = {
    "MNIST": ((0.5,), (0.5,)),
    "FashionMNIST": ((0.5,), (0.5,)),
    "EMNIST": ((0.5,), (0.5,)),
    "CIFAR10": ((0.4914, 0.4822, 0.4465), (0.2471, 0.2435, 0.2616)),
    "CIFAR100": ((0.4914, 0.4822, 0.4465), (0.2471, 0.2435, 0.2616)),
}


def get_image_normalization(dataset_name):
    # Shared source of image mean/std values used by attacks in normalized model space.
    if dataset_name is None:
        return None
    return IMAGE_DATASET_NORMALIZATION.get(str(dataset_name))
