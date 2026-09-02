import boto3
import json
import time

session = boto3.Session(profile_name="careharmony-main", region_name="us-east-1")
logs = session.client("logs")
contact_id = "74379f98-1afe-4b15-8b95-034a2a5cbdd6"

log_groups = [
    "/aws/lex/cara-health-bot-conversations-258673",
    "/aws/connect/cara-health-bot-258673",
]

for lg in log_groups:
    print(f"\n==================== Log Group: {lg} ====================")
    try:
        q_resp = logs.start_query(
            logGroupName=lg,
            startTime=int(time.time()) - 14400,
            endTime=int(time.time()) + 600,
            queryString=f'fields @timestamp, @message | filter @message like "{contact_id}" | sort @timestamp asc | limit 200'
        )
        query_id = q_resp["queryId"]
        for _ in range(15):
            res = logs.get_query_results(queryId=query_id)
            if res["status"] in {"Complete", "Failed", "Cancelled"}:
                break
            time.sleep(1)
        results = res.get("results", [])
        print(f"Results found: {len(results)}")
        for r in results:
            msg = next((c["value"] for c in r if c["field"] == "@message"), "")
            print(msg)
    except Exception as e:
        print("Error querying:", e)
