import os


class Utils:
    def __init__(self):
        self.init()

    @classmethod
    def check_path(cls, base_path, relative_path):
        full_path = os.path.normpath(os.path.join(base_path, relative_path))
        base_path = os.path.normpath(base_path)

        if not full_path.startswith(base_path):
            raise Exception("Not allowed")
        return full_path
