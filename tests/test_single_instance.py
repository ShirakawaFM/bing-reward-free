from __future__ import annotations

import os
import subprocess
import sys
import unittest

_HOLD = """
import sys, time
from rewards_bot.single_instance import acquire_single_instance

print("1" if acquire_single_instance() else "0", flush=True)
if len(sys.argv) > 1 and sys.argv[1] == "hold":
    time.sleep(2.0)
"""

_CHECK = """
from rewards_bot.single_instance import acquire_single_instance

print("1" if acquire_single_instance() else "0", flush=True)
"""


@unittest.skipUnless(os.name == "nt", "单实例互斥量仅在 Windows 生效")
class SingleInstanceTests(unittest.TestCase):
    def test_second_process_is_rejected_until_first_exits(self) -> None:
        holder = subprocess.Popen(
            [sys.executable, "-c", _HOLD, "hold"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            self.assertIsNotNone(holder.stdout)
            self.assertEqual(holder.stdout.readline().strip(), "1")
            blocked = subprocess.run(
                [sys.executable, "-c", _CHECK],
                capture_output=True,
                text=True,
                timeout=20,
            )
            self.assertEqual(blocked.stdout.strip(), "0", blocked.stderr)
        finally:
            holder.wait(timeout=20)
            holder.stdout.close()
            holder.stderr.close()

        released = subprocess.run(
            [sys.executable, "-c", _CHECK],
            capture_output=True,
            text=True,
            timeout=20,
        )
        self.assertEqual(released.stdout.strip(), "1", released.stderr)


if __name__ == "__main__":
    unittest.main()
