import json, os, requests

def main():
    nodes = os.environ.get("NODES","http://localhost:5001,http://localhost:5002,http://localhost:5003").split(",")
    amt = int(os.environ.get("AMOUNT","200000"))  # milli-coins
    users = json.load(open("users.json"))

    for n in nodes:
        for u in users:
            r = requests.post(f"{n}/faucet", json={"user_id": u["user_id"], "amount": amt}, timeout=5)
            r.raise_for_status()
        print(f"Funded {len(users)} users on {n} with {amt} milli")

if __name__ == "__main__":
    main()