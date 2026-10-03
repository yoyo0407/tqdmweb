from time import sleep

from qtqdm import Qtqdm


progress = Qtqdm(range(20), description="Example task")
try:
    with progress:
        for item in progress:
            sleep(0.2)
            progress.set_postfix(loss=round(1 / (item + 1), 3))
finally:
    progress.wait()
