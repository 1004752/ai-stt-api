import json
import os
from openai import OpenAI
from dotenv import load_dotenv

# .env 설정 불러오기
load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

channel_number = "1"

with open(f"{channel_number}_realtime.json", "r") as f:
    match_json = json.load(f)

with open(f"{channel_number}_player.json", "r") as f:
    player_json = json.load(f)

home_info = f"""
    home team: {match_json.get("home_team").get("name")}
    home players: {[key for key, value in player_json.items() if value == "home"]}
"""

print(home_info)

away_info = f"""
    away team: {match_json.get("away_team").get("name")}
    away players: {[key for key, value in player_json.items() if value == "away"]}
"""

print(away_info)

model = "ft:gpt-3.5-turbo-0125:personal:ai-soccer-002:9JEmHnWh"

system_content = f"""
    너는 유능한 축구중계 데이터 분석가야. 너는 축구 중계 요약 코멘트를 json형태의 데이터로 변환해야해.
    아래 홈팀, 어웨이팀 정보를 참고해.
    
    {home_info}
    
    {away_info}
"""
# prompt = "Are you open on Monday?"
# assistant_content = "On Monday, location0, location1, and location2 open at 9 am, 8 am, and 8 am respectively."

client = OpenAI()

timelines = match_json.get("timeline")

for timeline in timelines:

    time = timeline.get("time")
    desc = timeline.get("desc")

    response = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": f"[{time}]{desc}"},
        ]
    )

    parse_out = response.choices[0].message.content
    print(parse_out)
