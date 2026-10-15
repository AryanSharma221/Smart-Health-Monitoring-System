import httpx

headers = {'Authorization': 'Bearer demo_offline_token_p101_p105', 'Content-Type': 'application/json'}
payload = {
    'sql': "SELECT reading_id, event_id, patient_id, metric_code, value, unit FROM vitals_readings WHERE patient_id = 'P101' LIMIT 2;",
    'is_demo_mode': True
}
resp = httpx.post('http://127.0.0.1:8000/api/v1/evaluation/workbench/execute', headers=headers, json=payload)
print('DEMO OFFLINE TOKEN STATUS:', resp.status_code)
print('STATUS FIELD:', resp.json().get('status'))
print('ROW COUNT:', resp.json().get('row_count'))
assert resp.status_code == 200
assert resp.json().get('status') == 'success'
print('DEMO OFFLINE TOKEN TEST: PASSED 100%!')
