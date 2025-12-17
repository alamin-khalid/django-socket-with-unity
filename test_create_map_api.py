"""
Test script for Map Creation API endpoint
Tests POST /api/map/create/ with validation
"""

import requests
import json
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"
API_ENDPOINT = f"{BASE_URL}/api/map/create/"

def test_create_map_success():
    """Test successful map creation"""
    print("\n=== Test 1: Create Map Successfully ===")
    
    next_time = (datetime.now() + timedelta(hours=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    data = {
        "map_id": f"planet_test_{timestamp}",
        "season_id": 1,
        "round_id": 0,
        "current_round_number": 0
    }
    
    response = requests.post(API_ENDPOINT, json=data, headers={"Content-Type": "application/json"})
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    print("✅ Test passed!")
    return data["map_id"]

def test_create_duplicate_map(map_id):
    """Test duplicate map_id validation"""
    print("\n=== Test 2: Duplicate Map ID (Should Fail) ===")
    
    next_time = (datetime.now() + timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    
    data = {
        "map_id": map_id,  # Use same ID from test 1
        "season_id": 1,
        "round_id": 1,
        "current_round_number": 1,
        "next_round_time": next_time
    }
    
    response = requests.post(API_ENDPOINT, json=data, headers={"Content-Type": "application/json"})
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 409, f"Expected 409 Conflict, got {response.status_code}"
    assert "already exists" in response.json().get("error", ""), "Expected duplicate error message"
    print("✅ Test passed!")

def test_default_datetime():
    """Test map creation without next_round_time (should default to now)"""
    print("\n=== Test 3: Default Datetime (Should Success) ===")
    
    timestamp = datetime.now().strftime("%Y%m%d%H%M%S")
    data = {
        "map_id": f"planet_test_auto_{timestamp}",
        "season_id": 1
    }
    
    response = requests.post(API_ENDPOINT, json=data, headers={"Content-Type": "application/json"})
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 201, f"Expected 201, got {response.status_code}"
    # Verify next_round_time was set
    assert "next_round_time" in response.json()
    print("✅ Test passed! (next_round_time automatically set)")
    return data["map_id"]



def test_get_created_map(map_id):
    """Test retrieving the created map"""
    print(f"\n=== Test 5: GET /api/map/{map_id}/ ===")
    
    response = requests.get(f"{BASE_URL}/api/map/{map_id}/")
    
    print(f"Status Code: {response.status_code}")
    print(f"Response: {json.dumps(response.json(), indent=2)}")
    
    assert response.status_code == 200, f"Expected 200, got {response.status_code}"
    assert response.json()["map_id"] == map_id
    assert response.json()["status"] == "queued"
    print("✅ Test passed!")

def run_all_tests():
    """Run all tests"""
    print("=" * 50)
    print("Testing Map Creation API")
    print("=" * 50)
    
    try:
        # Test 1: Create map successfully
        map_id = test_create_map_success()
        
        # Test 2: Try to create duplicate
        test_create_duplicate_map(map_id)
        
        # Test 3: Default Datetime
        test_default_datetime()
        
        # Test 5: Retrieve created map
        test_get_created_map(map_id)
        
        print("\n" + "=" * 50)
        print("✅ All tests passed!")
        print("=" * 50)
        
    except AssertionError as e:
        print(f"\n❌ Test failed: {e}")
    except requests.exceptions.ConnectionError:
        print("\n❌ Error: Could not connect to server. Make sure Django is running on http://127.0.0.1:8000")
    except Exception as e:
        print(f"\n❌ Unexpected error: {e}")

if __name__ == "__main__":
    run_all_tests()
