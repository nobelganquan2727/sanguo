import os
import sys

# Add project root to path
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.graph_client import run_query
print(run_query("MATCH (e:Event) RETURN e LIMIT 5"))
