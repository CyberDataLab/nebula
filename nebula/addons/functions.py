import logging


def print_msg_box(msg, indent=1, width=None, title=None, logger_name=None):
    """Print message-box with optional title."""
    if logger_name:
        logger = logging.getLogger(logger_name)
    else:
        logger = logging.getLogger()

    if not isinstance(msg, str):
        raise TypeError("msg parameter must be a string")

    lines = msg.split("\n")
    space = " " * indent
    if not width:
        width = max(map(len, lines))
        if title:
            width = max(width, len(title))
    box = f"\n╔{'═' * (width + indent * 2)}╗\n"  # upper_border
    if title:
        if not isinstance(title, str):
            raise TypeError("title parameter must be a string")
        box += f"║{space}{title:<{width}}{space}║\n"  # title
        box += f"║{space}{'-' * len(title):<{width}}{space}║\n"  # underscore
    box += "".join([f"║{space}{line:<{width}}{space}║\n" for line in lines])
    box += f"╚{'═' * (width + indent * 2)}╝"  # lower_border
    logger.info(box)
