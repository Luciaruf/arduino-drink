import requests
import os
import json

# Airtable credentials from app.py
AIRTABLE_API_KEY = os.environ.get('AIRTABLE_API_KEY', 'patMvTkVAFXuBTZK0.73601aeaf05c4ffb8fc1109ffc1a7aa3d8e8bf740f094bb6f980c23aecbefeb5')
BASE_ID = 'appQZSlkfRWqALhaG'

def get_airtable_headers():
    return {
        'Authorization': f'Bearer {AIRTABLE_API_KEY}',
        'Content-Type': 'application/json'
    }

def test_user_consumazioni(user_id):
    print(f"\n=== Testing user_id: {user_id} ===")
    
    # Test different formulas
    formulas = [
        # Original formula
        f"{{User}}='{user_id}'",
        
        # First fix attempt
        f"FIND('{user_id}', ARRAYJOIN({{User}}, ',')) > 0",
        
        # Alternative approaches
        f"'{user_id}' IN {{User}}",
        f"SEARCH('{user_id}', ARRAYJOIN({{User}})) > 0",
        
        # Direct field access
        f"{{User}}.[0]='{user_id}'",
        
        # No filter - to see all records
        ""
    ]
    
    for formula in formulas:
        print(f"\n--- Testing formula: {formula if formula else 'NO FILTER'} ---")
        
        url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
        params = {}
        if formula:
            params['filterByFormula'] = formula
        
        response = requests.get(url, headers=get_airtable_headers(), params=params)
        
        print(f"Status code: {response.status_code}")
        data = response.json()
        
        if 'records' in data:
            records = data['records']
            print(f"Found {len(records)} records")
            
            # Print first 3 records for inspection
            for i, record in enumerate(records[:3]):
                print(f"Record {i+1}:")
                print(f"  ID: {record.get('id')}")
                print(f"  Fields: {json.dumps(record.get('fields', {}), indent=2)}")
        else:
            print("No records found or error in response")
            print(f"Response: {json.dumps(data, indent=2)}")

# Test with your user ID
test_user_consumazioni("recGVkeQyif4oNyOh")

# Also test with a different approach - get all records and filter manually
print("\n=== Manual filtering test ===")
url = f'https://api.airtable.com/v0/{BASE_ID}/Consumazioni'
response = requests.get(url, headers=get_airtable_headers())
data = response.json()

if 'records' in data:
    records = data['records']
    print(f"Total records: {len(records)}")
    
    # Manually filter for the user ID
    matching_records = []
    for record in records:
        fields = record.get('fields', {})
        users = fields.get('User', [])
        if "recGVkeQyif4oNyOh" in users:
            matching_records.append(record)
    
    print(f"Manually filtered records for user recGVkeQyif4oNyOh: {len(matching_records)}")
    
    # Print first 3 matching records
    for i, record in enumerate(matching_records[:3]):
        print(f"Matching Record {i+1}:")
        print(f"  ID: {record.get('id')}")
        print(f"  Fields: {json.dumps(record.get('fields', {}), indent=2)}")
