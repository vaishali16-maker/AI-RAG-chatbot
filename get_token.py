import os
from getpass import getpass

import requests
from dotenv import load_dotenv

load_dotenv("backend/.env")
url = os.environ["SUPABASE_URL"]
key = os.environ["SUPABASE_PUBLISHABLE_KEY"]
r = requests.post(
    f"{url}/auth/v1/token?grant_type=password",
    headers={"apikey": key, "Content-Type": "application/json"},
    json={"email": input("email: "), "password": getpass("password: ")},
)
print(r.json().get("access_token") or r.text)