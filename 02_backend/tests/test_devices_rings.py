def test_two_device_rings():
    from data_generation.generate_synthetic_data import gen_devices
    accounts = [{"account_id": "ACC-NIGHTFALL-001"}] + [
        {"account_id": f"ACC-NETWORK-{i:03d}"} for i in range(1, 9)]
    devs = gen_devices(accounts)
    fp = {d["account_id"]: d["device_fingerprint"] for d in devs if d["account_id"].startswith("ACC-N")}
    ring1 = {a for a, f in fp.items() if f == "FP-NIGHTFALL-SHARED-001"}
    ring2 = {a for a, f in fp.items() if f == "FP-NIGHTFALL-SHARED-002"}
    assert "ACC-NIGHTFALL-001" in ring1 and "ACC-NETWORK-001" in ring1
    assert "ACC-NETWORK-005" in ring2 and "ACC-NETWORK-008" in ring2
    assert ring1.isdisjoint(ring2)
