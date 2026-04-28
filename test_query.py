from agent.graph_client import run_query
print(run_query("MATCH (e:Event) RETURN e LIMIT 5"))
