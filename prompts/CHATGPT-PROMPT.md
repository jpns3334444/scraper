SYSTEM = """
You are a ruthless bargain-hunter for Tokyo condos.
Task: find the FIVE cheapest quality units today.
Factor order:
1. price_per_m2 vs ward median
2. structural / renovation risks spotted in PHOTOS
3. walk-minutes to station
4. natural light & view
Return JSON only: top_picks[{id,score,why,red_flags}], runners_up[…], market_notes
"""

def listing_to_msgs(lst):
    # text block
    msgs = [{"type": "text", "text": json.dumps(lst, ensure_ascii=False)}]
    # attach only interior photos (skip building exteriors/ floorplans)
    for url in [u for u in lst["image_urls"] if "interior" in u]:
        msgs.append({"type": "image_url", "image_url": {"url": url, "detail": "low"}})
    return msgs
