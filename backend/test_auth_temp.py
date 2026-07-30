import sys
import asyncio
from fastapi.testclient import TestClient
from api.main import app
from database import SessionLocal, User, AuthSession

client = TestClient(app)

def run_tests():
    print("Testing Registration...")
    res = client.post("/auth/register", json={
        "email": "testuser@example.com",
        "password": "Password123!",
        "display_name": "Test User"
    })
    
    if res.status_code == 200:
        print("Registration OK:", res.json())
    elif res.status_code == 409:
        print("User already registered (expected if ran before).")
    else:
        print("Registration Failed:", res.status_code, res.text)
        
    print("\nTesting Login...")
    res_login = client.post("/auth/login", json={
        "email": "testuser@example.com",
        "password": "Password123!"
    })
    
    if res_login.status_code == 200:
        print("Login OK:", res_login.json())
        cookie = res_login.cookies.get("basira_sid")
        print("Cookie set:", "basira_sid" in res_login.cookies)
        
        print("\nTesting /auth/me...")
        res_me = client.get("/auth/me", cookies={"basira_sid": cookie})
        print("Me OK:" if res_me.status_code == 200 else f"Me Failed: {res_me.status_code}")
        if res_me.status_code == 200:
            print(res_me.json())
            
        print("\nTesting Logout...")
        res_logout = client.post("/auth/logout", cookies={"basira_sid": cookie})
        print("Logout OK:", res_logout.json())
        
        print("\nTesting /auth/me after logout...")
        res_me2 = client.get("/auth/me", cookies={"basira_sid": cookie})
        print("Me after logout:", res_me2.status_code, res_me2.text)
        
    else:
        print("Login Failed:", res_login.status_code, res_login.text)

if __name__ == "__main__":
    run_tests()
