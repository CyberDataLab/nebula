import asyncio
import logging


async def debug_tasks():
    while True:
        tasks = asyncio.all_tasks()
        logging.info(f"Active tasks: {len(tasks)}")
        for task in tasks:
            logging.info(f"Task: {task}")
        await asyncio.sleep(5)
