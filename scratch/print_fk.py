import json

with open("scratch/mysql_integrity_verification_results.json", encoding="utf-8") as f:
    d = json.load(f)

for tbl, info in d["schema_details"]["tables"].items():
    if info["foreign_keys"]:
        fks_str = "; ".join([
            f"{fk['from']} -> {fk['table']}({fk['to']}) [ON DELETE {fk['on_delete']}]"
            for fk in info["foreign_keys"]
        ])
        print(f"{tbl}: {fks_str}")
