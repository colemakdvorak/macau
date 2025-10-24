import os
import requests
import json

# Straightforward. Access mempool and dump to file.
ENDPOINT_URL = os.environ["QUICKNODE_ENDPOINT"]

payload = json.dumps({"method":"txpool_content","id":1,"jsonrpc":"2.0"})

headers = {
  'Content-Type': 'application/json'
}

response = requests.request("POST", ENDPOINT_URL, headers=headers, data=payload)
response = response.json()

with open('sample.dump','w') as f:
    f.write(json.dumps(response))

