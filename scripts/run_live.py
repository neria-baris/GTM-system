"""Run the packaged ingestion-to-product workflow; never reads the frozen demo."""
from __future__ import annotations

import argparse
import importlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
REQUIRED = ('NOTION_API_KEY', 'AIRTABLE_TOKEN', 'OPENAI_API_KEY', 'JEV_API_KEY')
DEFAULTS = {'OPENAI_SEMANTIC_MODEL': 'gpt-6-luna', 'OPENAI_SEMANTIC_REASONING': 'medium',
            'JEV_REPEATS': '5', 'JEV_MAX_CONCURRENCY': '3', 'OPENAI_SEMANTIC_MAX_CONCURRENCY': '8'}
RESOURCES = ('config/routing_policy.json', 'config/tracker.json', 'schemas/presentation_v1.schema.json',
             'experiments/extraction/frozen_v1.json', 'context/audit_evidence.md',
             'src/extraction/semantic_llm.py', 'src/extraction/semantic_schema.py',
             'src/extraction/llm_adapter.py', 'src/extraction/benchmark.py')


def configure():
    from dotenv import load_dotenv
    load_dotenv(ROOT / '.env', override=True)  # configured keys win over machine-wide variables
    for key, value in DEFAULTS.items():
        if not os.environ.get(key):
            os.environ[key] = value


def audit_resources():
    for relative in RESOURCES:
        if not (ROOT / relative).is_file():
            raise ValueError('Missing packaged resource: ' + relative)
    imported = []
    for path in sorted((ROOT / 'src').rglob('*.py')):
        parts = list(path.relative_to(ROOT).with_suffix('').parts)
        if parts[-1] == '__init__':
            parts.pop()
        name = '.'.join(parts)
        module = importlib.import_module(name)
        if not Path(module.__file__).resolve().is_relative_to(ROOT):
            raise ValueError('Import escaped package: ' + name)
        imported.append(name)
    policy = json.loads((ROOT / 'config/routing_policy.json').read_text(encoding='utf-8'))
    if policy['verified_actual_usd_mutation_allowed'] is not False or policy['candidate_proposals_for_review']:
        raise ValueError('Routing configuration contains forbidden verification or recorded proposals')
    return imported


def commands(port=8878, serve=True, notion_export=None, crm_export=None):
    py = sys.executable
    result = [
        ('Read source evidence', [py, '-B', '-m', 'src.connectors.sync_cli', '--require-live', '--mode', 'full']
         + (['--notion-export', str(notion_export)] if notion_export else [])
         + (['--crm-export', str(crm_export)] if crm_export else [])),
        ('Extract supported candidates', [py, '-B', '-m', 'src.extraction.full_corpus', '--require-jev', '--llm', 'auto']),
        ('Persist canonical state', [py, '-B', 'scripts/run_stage_c_full_corpus.py']),
        ('Validate canonical state', [py, '-B', 'scripts/validate_canonical_state.py', 'outputs/C/canonical_state.sqlite']),
        ('Build quantitative read model', [py, '-B', 'scripts/build_stage_d.py']),
        ('Validate presentation contract', [py, '-B', 'scripts/validate_presentation_contract.py', 'outputs/D/runtime', '--sqlite', 'data/runtime/gtm_state.sqlite']),
        ('Build frontend', [py, '-B', 'scripts/check_presentation_app.py', '--app', 'app', '--runtime', 'outputs/D/runtime', '--output', 'outputs/product_build.json']),
    ]
    if serve:
        result.append(('Open live product', [py, '-B', '-m', 'runtime.live_server', '--port', str(port)]))
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check-only', action='store_true', help='Load configuration and imports; stop before any external call')
    parser.add_argument('--no-serve', action='store_true')
    parser.add_argument('--port', type=int, default=8878)
    parser.add_argument('--notion-export', type=Path, help='Notion workspace export zip used instead of the Notion API')
    parser.add_argument('--crm-export', type=Path, help='CRM export JSON used instead of the Airtable API')
    args = parser.parse_args(argv)
    configure()
    modules = audit_resources()
    export = args.notion_export or (Path(os.environ['NOTION_EXPORT_ZIP']) if os.environ.get('NOTION_EXPORT_ZIP') else None)
    if export and not export.is_file():
        raise ValueError('Notion export not found: ' + str(export))
    crm = args.crm_export or (Path(os.environ['CRM_EXPORT_JSON']) if os.environ.get('CRM_EXPORT_JSON') else None)
    if crm and not crm.is_file():
        raise ValueError('CRM export not found: ' + str(crm))
    replaced = {'NOTION_API_KEY': export, 'AIRTABLE_TOKEN': crm}
    missing = [key for key in REQUIRED if not os.environ.get(key) and not replaced.get(key)]
    if missing:
        print('Configuration incomplete. Set: ' + ', '.join(missing))
        print('No external calls made.')
        return 2
    for key in ('JEV_REPEATS', 'JEV_MAX_CONCURRENCY', 'OPENAI_SEMANTIC_MAX_CONCURRENCY'):
        if int(os.environ[key]) < 1:
            raise ValueError(key + ' must be a positive integer')
    if not shutil.which('node'):
        if os.environ.get('GTM_NODE_OPTIONAL') != '1':
            raise ValueError('Node.js 22+ is required for the frontend build check')
        # Packaged executable without Node: only the JavaScript syntax step is skipped and reported.
        print('Node.js not found (GTM_NODE_OPTIONAL=1): the frontend build check skips only its JavaScript syntax step.')
    print(f'Configuration loaded; {len(modules)} production modules and all runtime resources resolved locally.')
    if args.check_only:
        print('Live preflight PASS. Stopped before external calls; credential access/validity is not tested.')
        return 0
    # Do not accidentally mix stale live output with a new run. Demo is immutable and separate.
    if any((ROOT / 'outputs' / name).exists() for name in ('A2', 'C2', 'C', 'D')):
        raise ValueError('Existing live output found. Move outputs/ to a separate archive before starting another live run. Keep data/raw/ immutable.')
    destination = ROOT / 'outputs/B/routing_policy.json'
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ROOT / 'config/routing_policy.json', destination)
    for label, command in commands(args.port, not args.no_serve, export.resolve() if export else None,
                                   crm.resolve() if crm else None):
        print(label + '...', flush=True)
        subprocess.run(command, cwd=ROOT, check=True)
    return 0


if __name__ == '__main__':
    try:
        raise SystemExit(main())
    except subprocess.CalledProcessError as exc:
        raise SystemExit(f'Live workflow stopped: command failed with exit code {exc.returncode}. No subsequent step ran.')
    except (ValueError, OSError, ImportError) as exc:
        raise SystemExit(str(exc))
