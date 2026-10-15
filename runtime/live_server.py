"""Serve only the freshly validated live read model through the existing product."""
import argparse
import signal
from pathlib import Path

from runtime.server import ROOT, DATA, Handler, Server
from scripts.validate_presentation_contract import validate


class LiveHandler(Handler):
    def translate_path(self, path):
        relative = path.split('?', 1)[0].removeprefix('/')
        if relative in DATA:
            return str(ROOT / 'outputs/D/runtime' / Path(relative).name)
        return super().translate_path(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--port', type=int, default=8878)
    args = parser.parse_args()
    validate(ROOT / 'outputs/D/runtime', ROOT / 'data/runtime/gtm_state.sqlite')
    with Server(('127.0.0.1', args.port), LiveHandler) as server:
        print(f'Live product: http://127.0.0.1:{server.server_port}/app/', flush=True)
        print('Current live results; frozen demo is unchanged. Press Ctrl+C to stop.', flush=True)
        def stop(signum, frame):
            raise KeyboardInterrupt
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, stop)
        try:
            server.serve_forever()
        except KeyboardInterrupt:
            print('Live product stopped.', flush=True)


if __name__ == '__main__':
    main()
