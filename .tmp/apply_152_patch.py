from pathlib import Path

path = Path("services/actions/worker.py")
text = path.read_text()
text = text.replace("    return ads\n\n\n\ndef load_action_readiness", "    return ads\n\n\ndef load_action_readiness")
text = text.replace("    return row[\"readiness_state\"], row[\"verification_level\"]\n\ndef persist_rotated", "    return row[\"readiness_state\"], row[\"verification_level\"]\n\n\ndef persist_rotated")
text = text.replace("    )\n\n\n\ndef record_apply_start", "    )\n\n\ndef record_apply_start")
text = text.replace("            ),\n        )\n\ndef persist_apply_result", "            ),\n        )\n\n\ndef persist_apply_result")
path.write_text(text)
