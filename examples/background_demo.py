"""A ten-minute run for checking that Android keeps working with the screen off.

Start it, leave the app, and lock the phone. The notification should stay up
and the log should keep growing. Stop or Kill ends it early.
"""

import time

print("background demo started", flush=True)
for i in range(600):
    print(f"still going {i}", flush=True)
    time.sleep(1)
print("background demo finished", flush=True)
