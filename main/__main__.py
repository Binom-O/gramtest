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

async def mutltithreading() -> tuple[any]:
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

    for gpu_id in range(config.gpu_count):
        if count == config.gpu_count:
            break

        giver_address = random.choice(list(set(givers_list) - givers_in_use))
        givers_in_use.add(giver_address)

        seed, complexity = await get_pow_params(giver_address)
        tasks.append(asyncio.shield(pow_init(gpu_id, giver_address, seed, complexity)))
        count += 1

    return await asyncio.gather(*tasks, return_exceptions=True)

async def send_message(wallet: WalletV4R2) -> WalletMessage | None:
    for (gpu_id, (boc, giver_address)) in enumerate(await mutltithreading()):
        if boc is not None:
            try:
                return wallet.create_wallet_internal_message(
                    destination=Address(giver_address),
                    value=int(0.05 * 1e9),
                    body=Cell.from_boc(boc)[0].to_slice().load_ref(),
                )
            except BocError:
                continue
    return None

async def main():
    await provider.start_up()
    wallet = await WalletV4R2.from_mnemonic(provider, config.mnemonics)
    
    while True:
        try:
            for (gpu_id, (boc, giver_address)) in enumerate(await mutltithreading()):
                if boc is not None:
                    seed, _ = await get_pow_params(giver_address)
                    seed = str(seed)[:4]
                    print(f"GPU {gpu_id}, Seed {seed} - Mined! Sending messages...")
                    message = await send_message(wallet)
                    await wallet.raw_transfer(msgs=[message])
                else:
                    print(f"GPU - {gpu_id}, Seed {seed} - Not mined. Retrying...")
        except Exception as e:
            traceback.print_exc()
            print(e)

if __name__ == "__main__":
    asyncio.run(main())