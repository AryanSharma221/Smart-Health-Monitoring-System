import httpx

resp = httpx.post('http://127.0.0.1:8000/api/v1/auth/login', json={'email': 'doctor@hospital.org', 'password': 'DoctorPassword123!'})
token = resp.json()['access_token']
headers = {'Authorization': f'Bearer {token}'}

# Insert
resp_ins = httpx.post('http://127.0.0.1:8000/api/v1/evaluation/workbench/execute', headers=headers, json={
    'sql': "INSERT INTO vitals_readings (patient_id, metric_code, value, unit) VALUES ('P101', 'heart_rate', 133.0, 'bpm');",
    'is_demo_mode': True
})
print('INSERT:', resp_ins.status_code, resp_ins.json().get('last_inserted_id'))
ins_id = resp_ins.json().get('last_inserted_id')

# Subquery DELETE
sub_del = "DELETE FROM vitals_readings WHERE reading_id = (SELECT reading_id FROM vitals_readings v JOIN ingestion_events e ON v.event_id = e.event_id WHERE e.source = 'self_added' ORDER BY v.measured_at DESC LIMIT 1);"
resp_del = httpx.post('http://127.0.0.1:8000/api/v1/evaluation/workbench/execute', headers=headers, json={
    'sql': sub_del,
    'is_demo_mode': True
})
print('SUBQUERY DELETE:', resp_del.status_code, resp_del.json())
