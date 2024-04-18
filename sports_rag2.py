import json
import os
os.environ["OPENAI_API_KEY"] = "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"

from langchain_openai import OpenAI
from langchain.prompts import FewShotPromptTemplate, PromptTemplate
from langchain.prompts.example_selector import SemanticSimilarityExampleSelector
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings

example_prompt = PromptTemplate(
    input_variables=["input", "output"],
    template="Input: {input}\nOutput: {output}",
)

# These are a lot of examples of a pretend task of creating antonyms.
examples = [
    {"input": "[[HT]]경기가 종료되었습니다.", "output": """{{
      "team": "none",
      "desc": "경기가 종료되었습니다."
    }}"""},
    {"input": "[[+7']]아스날, 자기 진영에서의 프리킥.", "output": """{{
      "team": "away",
      "time": "+7'",
      "desc": "아스톤 빌라, 자기 진영에서 프리킥 기회를 얻었습니다."
    }}"""},
    {"input": "[[+6']]데이빗 쿠트 주심, 아스톤 빌라 에게 프리킥 판정.", "output": """{{
      "team": "away",
      "time": "+6'",
      "desc": "데이빗 쿠트 주심, 아스톤 빌라 에게 프리킥 판정."
    }}"""},
    {"input": "[[+5']]아스날, 데클런 라이스의 슛이 나오지만 빗나갑니다.", "output": """{{
      "team": "home",
      "time": "+5'",
      "desc": "아스날, 데클런 라이스의 슛이 나오지만 빗나갑니다."
    }}"""},
    {"input": "[[+4']]데이빗 쿠트 주심, 아스톤 빌라의 레온 베일리에게 오프사이드 판정을 내립니다.", "output": """{{
      "team": "away",
      "time": "+4'",
      "desc": "데이빗 쿠트 주심, 아스톤 빌라의 레온 베일리에게 오프사이드 판정을 내립니다."
    }}"""},
    {"input": "[[+3']]아스톤 빌라, 자기 진영에서의 프리킥.", "output":  """{{
      "team": "away",
      "time": "+3'",
      "desc": "아스톤 빌라, 자기 진영에서의 프리킥."
    }}"""},
    {"input": "[[+1']]후반전 추가 시간은 8분 입니다.", "output":  """{{
      "team": "none",
      "time": "+1'",
      "desc": "후반전 추가 시간은 8분 입니다."
    }}"""},
    {"input": "[[87']]아스날, 올렉산드르 진첸코 빼고 에드워드 은케티아투입합니다. 다섯번째 선수교체.", "output": """{{
      "team": "home",
      "time": "87'",
      "in": "은케티아",
      "out": "진첸코",
      "name": "은케티아 투입",
      "desc": "아스날, 올렉산드르 진첸코 빼고 에드워드 은케티아투입합니다. 다섯번째 선수교체."
    }}"""},
    {"input": "[[87']]유리 틸레만스의 도움으로 기록됩니다.", "output": """{{
      "team": "away",
      "time": "87'",
      "name": "유리 틸레만스 도움",
      "desc": "유리 틸레만스의 도움으로 기록됩니다."
    }}"""},
    {"input": "[[87']]골! 올리 왓킨스의 골로 아스톤 빌라 , 0-2까지 점수차를 벌립니다.", "output":  """{{
      "team": "away",
      "time": "87'",
      "name": "올리 왓킨스",
      "desc": "골! 올리 왓킨스의 골로 아스톤 빌라 , 0-2까지 점수차를 벌립니다."
    }}"""},
    {"input": "[[84']]아스톤 빌라의 코너킥을 선언하는 데이빗 쿠트 주심.", "output":  """{{
      "team": "away",
      "time": "84'",
      "desc": "아스톤 빌라의 코너킥을 선언하는 데이빗 쿠트 주심."
    }}"""},
    {"input": "[[80']]우나이 에메리(아스톤 빌라) 감독의 두 번째 선수 교체. 로페라 알렉스 모레노, 부상당한 니콜로 자니올로 대신 들어갑니다.", "output":  """{{
      "team": "away",
      "time": "80'",
      "in": "알렉스 모레노",
      "out": "니콜로 자니올로",
      "name": "알렉스 모레노 투입",
      "desc": "우나이 에메리(아스톤 빌라) 감독의 두 번째 선수 교체. 로페라 알렉스 모레노, 부상당한 니콜로 자니올로 대신 들어갑니다."
    }}"""},
    {"input": "[[79']]아스날, 가브리에우 제주스대신 파비우 비에이라 들어갑니다. 네번째 선수교체.", "output":  """{{
      "team": "home",
      "time": "79'",
      "in": "비에이라",
      "out": "가브리에우 제주스",
      "name": "비에이라 투입",
      "desc": "아스날, 가브리에우 제주스대신 파비우 비에이라 들어갑니다. 네번째 선수교체."
    }}"""},
    {"input": "[[63']]아스날의 카이 하베르츠, 경고를 받습니다.", "output":  """{{
      "team": "home",
      "time": "63'",
      "name": "하베르츠 경고",
      "desc": "아스날의 카이 하베르츠, 경고를 받습니다."
    }}"""},
    {"input": "[[+1']]아스날의 가브리에우 마갈량이스, 런던에서 경고를 받습니다.", "output":  """{{
      "team": "home",
      "time": "+1'",
      "name": "마갈량이스 경고",
      "desc": "아스날의 가브리에우 마갈량이스, 런던에서 경고를 받습니다."
    }}"""},
    {"input": "[[63']]아스톤 빌라의 모건 로저스, 경고입니다.", "output":  """{{
      "team": "away",
      "time": "63'",
      "name": "로저스 경고",
      "desc": "아스톤 빌라의 모건 로저스, 경고입니다."
    }}"""},
    {"input": "[[+6']]데이빗 쿠트 주심, 아스톤 빌라 에게 프리킥 판정.", "output":  """{{
      "team": "away",
      "time": "+6'",
      "desc": "데이빗 쿠트 주심, 아스톤 빌라 에게 프리킥 판정."
    }}"""},
]

with open('978_realtime.json', 'r') as f:
    match_json = json.load(f)

with open('978_player.json', 'r') as f:
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

home_info = home_info.replace("{", "{{")\
    .replace("}", "}}")\
    .replace("[", "[[")\
    .replace("]", "]]")
away_info = away_info.replace("{", "{{") \
    .replace("}", "}}") \
    .replace("[", "[[") \
    .replace("]", "]]")

example_selector = SemanticSimilarityExampleSelector.from_examples(
    examples,
    OpenAIEmbeddings(),
    Chroma,
    k=1
)

similar_prompt = FewShotPromptTemplate(
    example_selector=example_selector,
    example_prompt=example_prompt,
    prefix="""
        {home_info}
        -----
        {away_info}
        -----
        위 정보로 주어진 입력에 대해 유사한 유형을 찾아서 그 형태대로 아래와 같이 type, in, out 출력해줘.
    """,
    suffix="Input: {input}\nOutput:",
    input_variables=["match_info", "input"],
)

llm = OpenAI()

for i, time_line in enumerate(match_json.get("timeline")):
    if time_line.get("state") == "change" or time_line.get("type") == "" or time_line.get("type") == "none":
        input_json = json.dumps(time_line, ensure_ascii=False)
        input = f"[{time_line.get('time')}]{time_line.get('desc')}".replace("{", "{{") \
            .replace("}", "}}") \
            .replace("[", "[[") \
            .replace("]", "]]")

        while True:
            try:
                answer = llm.invoke(
                    similar_prompt.format(
                        home_info=home_info,
                        away_info=away_info,
                        input=input
                    )
                )
                new_time_line = json.loads(answer)
                print(new_time_line)

                new_type = new_time_line.get("team")
                new_in = new_time_line.get("in")
                new_out = new_time_line.get("out")
                new_time = new_time_line.get("time", "0")
                new_desc = new_time_line.get("desc")

                # if int(new_time.replace("'", "").replace("none", "0")) > 0:
                #     match_json.get("timeline")[i].get("type").update(new_type)
                #     if match_json.get("timeline")[i].get("state") == "change" and new_in and new_out:
                #         match_json.get("timeline")[i].get("in").update(new_in)
                #         match_json.get("timeline")[i].get("out").update(new_out)
                #

                break
            except:
                continue
