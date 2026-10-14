"""Create a local-only pairing file; print only the server's token hash and owner ID."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import shutil
import sys

from personal_chat_image_worker import validate_config


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--site-url', required=True)
    parser.add_argument('--owner-id', required=True, help='Exact, verified LearnLoop account ID')
    parser.add_argument('--node-path', default=shutil.which('node'))
    parser.add_argument('--cli-path', required=True, help='Installed official chrome-devtools.js executable')
    parser.add_argument('--downloads-dir', type=Path, required=True)
    parser.add_argument('--state-dir', type=Path, required=True)
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_-]{1,64}', args.owner_id):
        parser.error('Invalid owner ID')
    root = args.state_dir.resolve()
    config_path = root/'worker.json'
    if config_path.exists():
        parser.error('Pairing file already exists; refusing to rotate its token implicitly')
    config = validate_config({'site_url':args.site_url, 'worker_token':secrets.token_urlsafe(48),
        'node_path':str(args.node_path or ''), 'cli_path':str(Path(args.cli_path).resolve()),
        'downloads_dir':str(args.downloads_dir.resolve()), 'state_dir':str(root),
        'python_path':sys.executable})
    root.mkdir(parents=True,exist_ok=True)
    descriptor = os.open(config_path, os.O_WRONLY|os.O_CREAT|os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
        json.dump(config,handle,ensure_ascii=False,indent=2)
    print(f'Local pairing saved: {config_path}')
    print('Add these values to the server private environment, then restart through deployment:')
    print('PERSONAL_CHAT_IMAGE_ENABLED=true')
    print('PERSONAL_CHAT_IMAGE_OWNER_ID='+args.owner_id)
    print('PERSONAL_CHAT_IMAGE_WORKER_TOKEN_SHA256='+hashlib.sha256(config['worker_token'].encode()).hexdigest())


if __name__ == '__main__':
    main()
