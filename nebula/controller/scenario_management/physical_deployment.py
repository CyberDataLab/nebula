# nebula/controller/scenario_management/physical_deployment.py
# ============================================================

from __future__ import annotations

import asyncio
import logging
import os
from urllib.parse import quote

from aiohttp import FormData

from nebula.controller.http_helpers import remote_get, remote_post_form

from .deployment_interface import DeploymentInterface


class PhysicalDeployment(DeploymentInterface):
    """
    Deployment on real hardware using the controller endpoints:
        • PUT /physical/setup/{ip:port}
        • GET /physical/run/{ip:port}
        • GET /physical/stop/{ip:port}
    """

    # ---------------------------------------------------------- #
    def __init__(self, sm):
        super().__init__(sm)
        port = os.getenv("NEBULA_CONTROLLER_PORT", "49152")
        self.controller_host = f"127.0.0.1:{port}"

    # ---------------------------------------------------------- #
    def start_blockchain(self) -> None:
        if self.sm.use_blockchain:
            self.sm._start_blockchain_impl()

    # ---------------------------------------------------------- #
    async def _upload_and_start(self, node_cfg: dict) -> None:
        ip = node_cfg["network_args"]["ip"]
        port = node_cfg["network_args"]["port"]
        host = f"{ip}:{port}"
        idx = node_cfg["device_args"]["idx"]

        cfg_dir = self.sm.config_dir
        config_path = f"{cfg_dir}/participant_{idx}.json"
        global_test_path = f"{cfg_dir}/global_test.h5"
        train_set_path = f"{cfg_dir}/participant_{idx}_train.h5"

        # ---------- multipart/form-data ------------------------
        form = FormData()
        form.add_field(
            "config", open(config_path, "rb"), filename=os.path.basename(config_path), content_type="application/json"
        )
        form.add_field(
            "global_test",
            open(global_test_path, "rb"),
            filename=os.path.basename(global_test_path),
            content_type="application/octet-stream",
        )
        form.add_field(
            "train_set",
            open(train_set_path, "rb"),
            filename=os.path.basename(train_set_path),
            content_type="application/octet-stream",
        )

        # ---------- /physical/setup/ (PUT) ---------------------
        setup_ep = f"/physical/setup/{quote(host, safe='')}"
        st, data = await remote_post_form(self.controller_host, setup_ep, form, method="PUT")
        if st != 201:
            raise RuntimeError(f"[{host}] setup failed – {st}: {data}")

        # ---------- /physical/run/ (GET) ------------------------
        run_ep = f"/physical/run/{quote(host, safe='')}"
        st, data = await remote_get(self.controller_host, run_ep)
        if st != 200:
            raise RuntimeError(f"[{host}] run failed – {st}: {data}")

        logging.info("Node %s running: %s", host, data)

    # ---------------------------------------------------------- #
    async def _deploy_all(self) -> None:
        await asyncio.gather(*(self._upload_and_start(n) for n in self.sm.config.participants))

    def start_nodes(self) -> None:
        logging.info("Deploying nodes on physical devices...")
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(self._deploy_all(), loop)
        except RuntimeError:
            asyncio.run(self._deploy_all())
        logging.info("All physical nodes deployed.")

    # ---------------------------------------------------------- #
    async def _stop_node(self, host: str) -> None:
        stop_ep = f"/physical/stop/{quote(host, safe='')}"
        st, data = await remote_get(self.controller_host, stop_ep)
        if st != 200:
            logging.warning("[%s] stop returned %s: %s", host, st, data)
        else:
            logging.info("[%s] successfully stopped (%s)", host, data)

    async def _stop_all(self) -> None:
        hosts = [f"{n['network_args']['ip']}:{n['network_args']['port']}" for n in self.sm.config.participants]
        await asyncio.gather(*(self._stop_node(h) for h in hosts))

    def stop_nodes(self) -> None:
        logging.info("Stopping physical nodes...")
        try:
            loop = asyncio.get_running_loop()
            asyncio.run_coroutine_threadsafe(self._stop_all(), loop)
        except RuntimeError:
            asyncio.run(self._stop_all())
