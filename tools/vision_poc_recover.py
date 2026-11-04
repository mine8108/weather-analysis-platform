"""Read and reconcile one existing background response; never create a generation."""
from pathlib import Path
from datetime import datetime, timezone
import json
import os
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from tools import vision_poc as poc

def reconcile(output, case_id, get_fn=None):
    import requests
    output = Path(output)
    lock = output / 'run.lock'
    fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
    try:
        os.write(fd, str(os.getpid()).encode())
        ledger = output / 'ledger.jsonl'
        states = poc.load_states(ledger)
        event = next(e for e in states.values() if e['case_id'] == case_id and e['alias'] == 'sol')
        if event['status'] not in {'background_poll_error', 'background_pending'}:
            raise ValueError('Only a pending or interrupted background response can be reconciled')
        model = event['model_config']
        assert model['api_format'] == 'responses_background'
        response_id = event['response_id']
        checkpoint = poc.read_json(output / 'response-checkpoints' / (event['job_id'] + '.json'))
        if checkpoint['response_id'] != response_id or checkpoint['job_id'] != event['job_id']:
            raise ValueError('Checkpoint identity mismatch')
        images, prompt, sources = poc.prepare_case(event['case'], Path(event['manifest_dir']), event['request_policy'])
        if poc.digest(prompt.encode()) != event['prompt_sha256'] or [s['submitted_sha256'] for s in sources] != [s['submitted_sha256'] for s in event['sources']]:
            raise ValueError('Original input changed; refusing reconciliation')
        started = time.monotonic()
        response = (get_fn or requests.get)(model['base_url'].rstrip('/') + '/responses/' + response_id,
            headers={'Authorization': 'Bearer ' + os.environ[model['key_env']].strip()},
            timeout=(10, 30), allow_redirects=False)
        if response.status_code != 200:
            return {'http_status': response.status_code, 'reconciled': False}
        data = response.json()
        if data['id'] != response_id:
            raise ValueError('Response identity mismatch')
        if data['status'] not in {'completed', 'incomplete'}:
            return {'response_status': data['status'], 'reconciled': False}
        visible = '\n'.join(part.get('text', '') for item in data.get('output', []) if item.get('type') == 'message'
                            for part in item.get('content', []) if part.get('type') == 'output_text')
        native = data.get('usage') or {}
        receipt = {'http_status': 200, 'request_id': event['request_id'],
                   'recovery_get_request_id': response.headers.get('x-request-id', ''),
                   'response_id': response_id, 'response_status': data['status'],
                   'data': {'usage': {'prompt_tokens': native.get('input_tokens'),
                     'completion_tokens': native.get('output_tokens'),
                     'completion_tokens_details': native.get('output_tokens_details'),
                     'prompt_tokens_details': native.get('input_tokens_details')},
                     'choices': [{'message': {'content': visible}, 'finish_reason': 'stop' if data['status'] == 'completed' else 'length'}]}}
        job = {'model_config': model, 'images': images, 'request_policy': event['request_policy']}
        result = poc.interpret_response(receipt, job)
        first = next(json.loads(line) for line in ledger.read_text(encoding='utf-8').splitlines()
                     if json.loads(line)['job_id'] == event['job_id'])
        updated = {**event, **result, 'recovered_via_same_response_id': True,
                   'initial_status': event['status'], 'initial_latency_seconds': event['latency_seconds'],
                   'recovery_get_latency_seconds': round(time.monotonic() - started, 3),
                   'latency_seconds': round((datetime.now(timezone.utc) - datetime.fromisoformat(first['at'])).total_seconds(), 3),
                   'at': poc.utc_now()}
        updated.pop('error_type', None)
        updated['budget_charge_usd'] = poc.usage_budget_usd(result['usage'], model) if result['usage'] else event['reservation_usd']
        poc.append_event(ledger, updated)
        return {'status': updated['status'], 'reconciled': True, 'new_generation_requests': 0}
    finally:
        os.close(fd)
        lock.unlink()

if __name__ == '__main__':
    for line in (ROOT / '.env.local').read_text(encoding='utf-8-sig').splitlines():
        name, sep, value = line.partition('=')
        if sep and name == 'OPENAI_API_KEY':
            os.environ[name] = value.strip()
    try:
        print(json.dumps(reconcile(ROOT / '.vision-poc/study', sys.argv[1]), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({'error_type': type(exc).__name__, 'reconciled': False}))
        raise SystemExit(2)
