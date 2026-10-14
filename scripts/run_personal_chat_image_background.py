"""Run the personal worker without a console, under an explicitly started Windows task."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

from personal_chat_image_worker import Worker, run, single_instance


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', type=Path, required=True)
    args = parser.parse_args()
    worker = Worker(json.loads(args.config.read_text(encoding='utf-8-sig')))
    with single_instance(worker.root):
        with (worker.root / 'worker.stdout.log').open('a', encoding='utf-8', buffering=1) as output, \
             (worker.root / 'worker.stderr.log').open('a', encoding='utf-8', buffering=1) as errors, \
             contextlib.redirect_stdout(output), contextlib.redirect_stderr(errors):
            pid_path = worker.root / 'worker.pid'
            pid_path.write_text(str(os.getpid()), encoding='ascii')
            (worker.root / 'stop.requested').unlink(missing_ok=True)
            try:
                print('正在连接普通 Chat；首次启动可能需要在 Chrome 中点允许。', flush=True)
                worker.keep_browser = True
                worker.connect()
                run(worker, SimpleNamespace(check_browser=False, once=False))
            except BaseException:
                import traceback
                traceback.print_exc()
                raise
            finally:
                if worker.browser_started:
                    worker.disconnect()
                if pid_path.exists() and pid_path.read_text(encoding='ascii').strip() == str(os.getpid()):
                    pid_path.unlink()


if __name__ == '__main__':
    main()
