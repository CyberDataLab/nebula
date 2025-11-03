class KafkaInitializationError(Exception):
    """Raised when client initialization fails."""
    pass

class KafkaExperimentInitializationError(Exception):
    """Raised when experiment initialization fails."""
    pass

class KafkaUserCreationError(Exception):
    """Raised when user creation fails."""
    pass

class KafkaUserDeletionError(Exception):
    """Raised when user deletion fails."""
    pass

class KafkaACLCreationError(Exception):
    """Raised when ACL creation fails."""
    pass

class KafkaACLDeletionError(Exception):
    """Raised when ACL deletion fails."""
    pass

class KafkaProducerError(Exception):
    """Raised when producer error occurs."""
    pass

class KafkaProducerInitializationError(Exception):
    """Raised when cannot initialize producer occurs."""
    pass

class KafkaTopicSubscriptionError(Exception):
    """Raised when topic subscription error occurs."""
    pass

class KafkaConsumerLoopError(Exception):
    """Raised when an error occurs on consumer loop."""
    pass

class KafkaLoadingConfigurationError(Exception):
    """Raised when an error occurs when loading configuration file."""
    pass

class KafkaConfigurationError(Exception):
    """Raised when an error occurs when configurating initial users."""
    pass