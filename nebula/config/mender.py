import base64
import json
import logging
import os

import requests


class Mender:
    def __init__(self):
        self.server = os.environ.get("MENDER_SERVER")
        self.user = os.environ.get("MENDER_USER")
        self.password = os.environ.get("MENDER_PASSWORD")
        self.token = os.environ.get("MENDER_TOKEN")
        logging.info(f"Mender server: {self.server}")

    def get_token(self):
        return self.token

    def renew_token(self):
        string = self.user + ":" + self.password
        base64string = base64.b64encode(string.encode("utf-8"))
        headers = {
            "Accept": "application/json",
            "Authorization": "Basic {}".format(str(base64string, "utf-8")),
            "Content-Type": "application/json",
        }

        r = requests.post(f"{self.server}/api/management/v1/useradm/auth/login", headers=headers)
        self.token = r.text

    @staticmethod
    def generate_artifact(type_artifact, artifact_name, device_type, file_path):
        os.system(
            f"mender-artifact write module-image -T {type_artifact} -n {artifact_name} -t {device_type} -o {artifact_name}.mender -f {file_path}"
        )

    def get_artifacts(self):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(f"{self.server}/api/management/v1/deployments/artifacts", headers=headers)

        logging.info(json.dumps(r.json(), indent=2))

    def upload_artifact(self, artifact_path, description):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        multipart_form_data = {
            "description": (None, f"{description}"),
            "artifact": (None, open(f"{artifact_path}", "rb")),
        }

        r = requests.post(
            f"{self.server}/api/management/v1/deployments/artifacts",
            files=multipart_form_data,
            headers=headers,
        )
        logging.info(r.text)

    def deploy_artifact_device(self, artifact_name, device):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type": "application/json",
        }

        json_req = {
            "artifact_name": f"{artifact_name}",
            "devices": [f"{device}"],
            "name": f"{device}",
            "all_devices": False,
        }

        r = requests.post(
            f"{self.server}/api/management/v1/deployments/deployments",
            json=json_req,
            headers=headers,
        )

        logging.info(r.text)

    def deploy_artifact_list(self, artifact_name, devices: list[str]):
        headers = {
            "Accept": "application/json",
            "Authorization": "Basic {}".format((self.user + ":" + self.password).encode("base64")),
            "Content-Type": "application/form-data",
        }

        json_req = {
            "artifact_name": f"{artifact_name}",
            "devices": devices,
            "name": "Example_deployment",
        }

        r = requests.post(
            f"{self.server}/api/management/v1/deployments/deployments",
            json=json_req,
            headers=headers,
        )

        logging.info(r.text)

    def get_info_deployment(self, deployment_id):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(
            f"{self.server}/api/management/v1/deployments/deployments/{deployment_id}",
            headers=headers,
        )

        logging.info(json.dumps(r.json(), indent=2))

    def get_my_info(self):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(f"{self.server}/api/management/v1/useradm/users/me", headers=headers)

        logging.info(json.dumps(r.json(), indent=2))

    def get_devices(self):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(
            f"{self.server}/api/management/v2/devauth/devices",
            params={"per_page": "300"},
            headers=headers,
        )

        logging.info(json.dumps(r.json(), indent=2))

    def get_devices_by_group(self, group):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        json_req = {
            "page": 1,
            "per_page": 300,
            "filters": [
                {
                    "scope": "system",
                    "attribute": "group",
                    "type": "$eq",
                    "value": group,
                },
                {
                    "scope": "identity",
                    "attribute": "status",
                    "type": "$eq",
                    "value": "accepted",
                },
            ],
            "sort": [],
            "attributes": [
                {"scope": "identity", "attribute": "status"},
                {"scope": "inventory", "attribute": "artifact_name"},
                {"scope": "inventory", "attribute": "device_type"},
                {"scope": "inventory", "attribute": "rootfs-image.version"},
                {"scope": "monitor", "attribute": "alerts"},
                {"scope": "system", "attribute": "created_ts"},
                {"scope": "system", "attribute": "updated_ts"},
                {"scope": "tags", "attribute": "name"},
                {"scope": "identity", "attribute": "name"},
            ],
        }

        r = requests.post(
            f"{self.server}/api/management/v2/inventory/filters/search",
            json=json_req,
            headers=headers,
        )

        logging.info(json.dumps(r.json(), indent=2))

        # json to file
        with open(f"devices_{group}.json", "w") as outfile:
            json.dump(r.json(), outfile, indent=2)

    def get_info_device(self, device_id):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(
            f"{self.server}/api/management/v1/inventory/devices/{device_id}",
            headers=headers,
        )

        logging.info(json.dumps(r.json(), indent=2))

    def get_connected_device(self, device_id):
        headers = {
            "Accept": "application/json",
            "Authorization": f"Bearer {self.get_token()}",
        }

        r = requests.get(
            f"{self.server}/api/management/v1/deviceconnect/devices/{device_id}",
            headers=headers,
        )

        logging.info(json.dumps(r.json(), indent=2))
