from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path
import requests
from environs import Env

BASE_DIR = Path(__file__).resolve().parent.parent

@dataclass
class Config:
    global_config: dict
    mnemonics: str
    recipient_address: str
    gpu_count: int
    timeout: int
    iterations: int
    givers_count: int
    boost_factor: int

    @classmethod
    def init(cls) -> Config:
        env = Env()
        env.read_env(f"{BASE_DIR}/.env")

        try:
            with open(f"{BASE_DIR}/data/global-config.json", "r") as file:
                global_config = json.load(file)
        except FileNotFoundError:
            global_config = requests.get('https://ton.org/global-config.json').json()

        return cls(
            global_config=global_config,
            mnemonics=env.str("seed"),
            recipient_address=env.str("target_address"),
            gpu_count=env.int("gpu_count"),
            timeout=env.int("timeout"),
            iterations=env.int("iterations"),
            givers_count=env.int("givers_count"),
            boost_factor=env.int("boost_factor"),
        )
