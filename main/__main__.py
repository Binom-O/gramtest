import asyncio
import os
import random
import secrets
import traceback
from asyncio import subprocess
from pathlib import Path
from pytoniq import LiteBalancer, WalletV4R2
from pytoniq_core import WalletMessage, Cell, Address
from pytoniq_core.boc.deserialize import BocError
from . import givers
from .config import Config, BASE_DIR

config = Config.init()
provider = LiteBalancer.from_config(config.global_config, trust_level=2)

async def get_pow_params(giver_address: str) -> tuple[int, int]:
    try:
        response = await provider.run_get_method(giver_address, "get_pow_params", [])
        return response[0], response[1]
    except Exception as e:
        return None, None



async def pow_init(gpu_id: int, giver_address: str, seed: int, complexity: int) -> tuple[bytes, str] | tuple[
    None, None]:
    filename = f"data/bocs/{secrets.token_hex()[:16]}.boc"
    command = (
        "./data/pow-miner-cuda" + f" -vv -g {gpu_id} -F {config.boost_factor} "
        f"-t {config.timeout} {config.recipient_address} {seed} "
        f"{complexity} {config.iterations} {giver_address} {filename}"
    )

    try:
        proc = await asyncio.create_subprocess_shell(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        await asyncio.wait_for(proc.wait(), config.timeout)

    except asyncio.TimeoutError:
        ...

    if Path(filename).exists():
        boc = Path(filename).read_bytes()
        os.remove(filename)
        return boc, giver_address

    return None, None

async def mutltithreading() -> list[tuple[bytes, str, str]]:
    tasks, count = [], 0
    givers_list = []  
    givers_in_use = set() 

    match config.givers_count:
        case 100:
            givers_list = givers.g100
        case 1000:
            givers_list = givers.g1000
        case _:
            raise ValueError("Invalid givers count")

    results = []
    for gpu_id in range(config.gpu_count):
        if count == config.gpu_count:
            break

        giver_address = random.choice(list(set(givers_list) - givers_in_use))
        givers_in_use.add(giver_address)

        seed, complexity = await get_pow_params(giver_address)
        boc, giver_address = await pow_init(gpu_id, giver_address, seed, complexity)
        if boc is not None:
            results.append((boc, giver_address, "mined"))
        else:
            results.append((None, giver_address, "not mined"))
        count += 1

    return results

async def send_messages(wallet: WalletV4R2, bocs: list[bytes], giver_addresses: list[str]) -> None:
    messages = []
    for boc, giver_address in zip(bocs, giver_addresses):
        if boc is not None:
            try:
                message = wallet.create_wallet_internal_message(
                    destination=Address(giver_address),
                    value=int(0.05 * 1e9),
                    body=Cell.from_boc(boc)[0].to_slice().load_ref(),
                )
                messages.append(message)
            except BocError:
                continue
    await wallet.raw_transfer(msgs=messages)

async def main():
    await provider.start_up()
    wallet = await WalletV4R2.from_mnemonic(provider, config.mnemonics)
    
    while True:
        try:
            results = await mutltithreading()
            for i in range(len(results)):
                boc, giver_address, status = results[i]
                if status == "mined":
                    seed, _ = await get_pow_params(giver_address)
                    seed = str(seed)[:4]
                    print(f"GPU {i}, Seed {seed} - Mined! Sending messages...")
                else:
                    print(f"GPU {i}, Not mined. Retrying...")
                    
            bocs, giver_addresses, _ = zip(*results)
            await send_messages(wallet, bocs, giver_addresses)
        except Exception as e:
            traceback.print_exc()
            print(e)

if __name__ == "__main__":
    asyncio.run(main())