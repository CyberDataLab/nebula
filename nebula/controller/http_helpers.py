from __future__ import annotations
 
import logging
from typing import Optional, Union
 
import aiohttp
from aiohttp import FormData
 
_TIMEOUT = aiohttp.ClientTimeout(total=15)
 
async def _request_json(
    method: str,
    host: str,
    endpoint: str,
    *,
    data: Optional[Union[FormData, bytes]] = None,
) -> tuple[int | None, object]:
    url = f"http://{host}{endpoint}"
    try:
        async with aiohttp.ClientSession(timeout=_TIMEOUT) as session:
            async with session.request(method.upper(), url, data=data) as resp:
                try:
                    payload = await resp.json()
                except Exception:
                    payload = await resp.text()
                return resp.status, payload
    except Exception as exc:
        logging.error("[%s] %s%s – %s", method.upper(), host, endpoint, exc)
        return None, str(exc)
 
 
async def remote_get(host: str, endpoint: str):
    return await _request_json("GET", host, endpoint)
 
 
async def remote_post_form(
    host: str,
    endpoint: str,
    form: FormData,
    *,
    method: str = "POST",
):
    return await _request_json(method, host, endpoint, data=form)