#!/usr/bin/env python3
"""Helper to launch XTTS fine-tuning from a prepared dataset manifest.

Expected dataset:
  <dataset_dir>/metadata.csv   (pipe-separated: wav_path|text)
  <dataset_dir>/wavs/*.wav
"""

import argparse
import shlex
import subprocess
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description='Launch XTTS fine-tuning (experimental).')
    parser.add_argument('--dataset-dir', required=True, help='Path with metadata.csv and wavs/')
    parser.add_argument('--output-dir', required=True, help='Directory for training outputs/checkpoints')
    parser.add_argument('--language', default='ru')
    parser.add_argument('--epochs', type=int, default=10)
    parser.add_argument('--batch-size', type=int, default=4)
    parser.add_argument('--run', action='store_true', help='Actually run training command (default: print only)')
    args = parser.parse_args()

    dataset_dir = Path(args.dataset_dir)
    metadata = dataset_dir / 'metadata.csv'
    wavs_dir = dataset_dir / 'wavs'

    if not metadata.exists():
        raise SystemExit(f'metadata.csv not found: {metadata}')
    if not wavs_dir.exists():
        raise SystemExit(f'wavs directory not found: {wavs_dir}')

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    cmd = [
        'python', '-m', 'TTS.bin.train_tts',
        '--continue_path', 'tts_models/multilingual/multi-dataset/xtts_v2',
        '--config_path', '',
        '--coqpit.output_path', str(output_dir),
        '--coqpit.datasets.0.path', str(dataset_dir),
        '--coqpit.datasets.0.meta_file_train', str(metadata.name),
        '--coqpit.datasets.0.language', args.language,
        '--coqpit.trainer.max_epochs', str(args.epochs),
        '--coqpit.trainer.batch_size', str(args.batch_size),
    ]

    printable = ' '.join(shlex.quote(c) for c in cmd)
    print('XTTS fine-tune command:')
    print(printable)

    if not args.run:
        print('\nDry run only. Add --run to execute.')
        return 0

    return subprocess.call(cmd, cwd=str(dataset_dir))


if __name__ == '__main__':
    raise SystemExit(main())
