import json
import os
import time

from langchain_openai import OpenAI
from langchain.prompts import FewShotPromptTemplate, PromptTemplate
from langchain.prompts.example_selector import SemanticSimilarityExampleSelector
from langchain_community.vectorstores import Chroma
from langchain_openai import OpenAIEmbeddings

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

game_number = "2024041951048615703"
channel_number = "978"

driver = webdriver.Chrome()


def get_team_info(match_info, team_type):
    team_info = {}

    if team_type == 0:
        team_index = 0
        team_info["name"] = match_info.find_elements(By.TAG_NAME, "em")[team_index].text[1:]
    else:
        team_index = 1
        team_info["name"] = match_info.find_elements(By.TAG_NAME, "em")[team_index].text
    team_info["logo"] = match_info.find_elements(By.TAG_NAME, "img")[team_index].get_attribute("src")
    return team_info


def get_player_name(players, desc_text, find_name):
    if players.get(find_name):
        out_player = ""
        for player in players:
            if player in desc_text:
                out_player = player.get("name")
                break
        return find_name, out_player, players.get(find_name)
    else:
        return find_name, "", ""


try:
    driver.get(f"https://m.sports.naver.com/game/{game_number}/lineup")

    content_member = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "content"))
    )

    game_sections = content_member.find_elements(By.TAG_NAME, "section")
    for section in game_sections:
        if "Home_game_panel" in section.get_attribute("class"):
            game_section = section

    game_section_divs = game_section.find_elements(By.TAG_NAME, "div")
    for div in game_section_divs:
        if "LineUp_home_team" in div.get_attribute("class"):
            home_lineup = div
        if "LineUp_away_team" in div.get_attribute("class"):
            away_lineup = div

    home_lineup_spans = home_lineup.find_elements(By.TAG_NAME, "span")
    away_lineup_spans = away_lineup.find_elements(By.TAG_NAME, "span")

    players = {}
    for span in home_lineup_spans:
        if "LineUp_name" in span.get_attribute("class"):
            players[span.text.strip()] = "home"

    for span in away_lineup_spans:
        if "LineUp_name" in span.get_attribute("class"):
            players[span.text.strip()] = "away"

    candidate_table = game_section.find_element(By.TAG_NAME, "table")
    candidate_trs = candidate_table.find_element(By.TAG_NAME, "tbody").find_elements(By.TAG_NAME, "tr")

    for tr in candidate_trs:
        home_candidate_name = tr.find_elements(By.TAG_NAME, "td")[0].find_elements(By.TAG_NAME, "span")[0].text.strip()
        away_candidate_name = tr.find_elements(By.TAG_NAME, "td")[1].find_elements(By.TAG_NAME, "span")[0].text.strip()
        players[home_candidate_name] = "home"
        players[away_candidate_name] = "away"

    time.sleep(1)

    driver.get(f"https://m.sports.naver.com/game/{game_number}/relay")

    content = WebDriverWait(driver, 10).until(
        EC.presence_of_element_located((By.ID, "content"))
    )

    match_realtime_data = {}
    match_highlight_data = {}

    match_sections = content.find_elements(By.TAG_NAME, "section")
    for section in match_sections:
        if "Home_game_head" in section.get_attribute("class"):
            match_head = section
        if "Home_game_panel" in section.get_attribute("class"):
            match_info = section

    home_info = get_team_info(match_head, 0)
    home_team_name = f"[홈팀]{home_info.get('name')}"
    away_info = get_team_info(match_head, 1)
    away_team_name = f"[원정팀]{away_info.get('name')}"

    match_realtime_data["home_team"] = home_info
    match_realtime_data["away_team"] = away_info
    match_highlight_data["home_team"] = home_info
    match_highlight_data["away_team"] = away_info

    buttons = match_info.find_elements(By.TAG_NAME, "a")
    for button in buttons:
        if "TimeLine_button" in button.get_attribute("class") \
                and button.get_attribute("aria-pressed") == "false":
            print(button.get_attribute("class"))
            button.click()
            time.sleep(1)
    #
    # open_button = content.find_element(By.XPATH,
    #                                    "/html/body/div/div[2]/div/div/div[1]/section[2]/div[2]/div[2]/div[2]/div[2]")
    # open_button.click()

    relay_list_areas = content.find_elements(By.CLASS_NAME, "relay_list_area")

    realtime_time_lines = []
    highlight_time_lines = []
    for relay_list_area in relay_list_areas:
        li_tags = relay_list_area.find_elements(By.TAG_NAME, "li")

        for li in li_tags:
            info_area = li.find_elements(By.TAG_NAME, "div")[0]
            time_box = info_area.find_element(By.TAG_NAME, "span")
            time_text = time_box.text.strip()

            relay_text_area = li.find_elements(By.TAG_NAME, "div")[1]
            desc_box = relay_text_area.find_element(By.TAG_NAME, "p")
            desc_text = desc_box.text.strip()

            time_line = {
                "time": time_text,
                "desc": desc_text,
                "type": "none" if time_text == "HT" or time_text else ""
            }

            state_box = info_area.find_elements(By.TAG_NAME, "span")
            if state_box and len(state_box) > 1:
                state = None
                try:
                    state = info_area.find_element(By.CLASS_NAME, "blind").text.strip()
                except:
                    state = ""
                if state == "골":
                    time_line["state"] = "goal"
                elif state == "자책골":
                    time_line["state"] = "owngoal"
                elif state == "도움":
                    time_line["state"] = "assistance"
                elif state == "교체":
                    time_line["state"] = "change"
                elif state == "경고":
                    time_line["state"] = "card1"
                elif "퇴장" in state:
                    time_line["state"] = "card2"
                elif time_text == "HT":
                    time_line["state"] = "quarter_finish1"
                elif not time_text:
                    time_line["state"] = "quarter_finish2"
                else:
                    time_line["state"] = "none"

            if time_line.get("state") in ["goal", "owngoal", "change", "card1", "card2", "quarter_finish1"]:
                if time_line.get("state") in ["goal", "owngoal", "change"]:
                    time_line["name"] = relay_text_area.find_element(By.TAG_NAME, "strong").text.strip()
                    if time_line.get("state") == "change":
                        time_line["in"] = ""
                        time_line["out"] = ""
                highlight_time_lines.append(time_line)
            realtime_time_lines.append(time_line)

    realtime_time_lines.reverse()
    highlight_time_lines.reverse()

    match_realtime_data["timeline"] = realtime_time_lines
    match_highlight_data["timeline"] = highlight_time_lines

    # 플레이어 저장
    file_name = f"{channel_number}_player.json"
    file_path = os.path.join(os.getcwd(), file_name)
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(json.dumps(players, ensure_ascii=False, indent=2))
    print(f"플레이어 파일이 저장되었습니다: {file_path}")

    # 실시간 경기 저장
    file_name = f"{channel_number}_realtime.json"
    file_path = os.path.join(os.getcwd(), file_name)
    with open(file_path, "w", encoding="utf-8") as file:
        file.write(json.dumps(match_realtime_data, ensure_ascii=False, indent=2))
    print(f"본경기 파일이 저장되었습니다: {file_path}")

    # 하이라이트 경기 저장
    file_name = f"{channel_number}_highlight.json"
    file_path = os.path.join(os.getcwd(), file_name)
    with open(file_path, "w") as file:
        file.write(json.dumps(match_highlight_data, ensure_ascii=False, indent=2))
    print(f"하이라이트 파일이 저장되었습니다: {file_path}")

finally:
    driver.quit()


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

home_info = home_info.replace("{", "{{") \
    .replace("}", "}}") \
    .replace("[", "[[") \
    .replace("]", "]]")
away_info = away_info.replace("{", "{{") \
    .replace("}", "}}") \
    .replace("[", "[[") \
    .replace("]", "]]")

example_selector = SemanticSimilarityExampleSelector.from_examples(
    examples,
    OpenAIEmbeddings(model="text-embedding-3-small"),
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

                new_type = new_time_line.get("team", "none")
                new_in = new_time_line.get("in")
                new_out = new_time_line.get("out")
                new_time = new_time_line.get("time", "0")
                new_desc = new_time_line.get("desc")

                if int(new_time.replace("'", "").replace("none", "0")) > 0:
                    if new_type not in ["none", "home", "away"]:
                        continue
                    match_json.get("timeline")[i]["type"] = new_type
                    if match_json.get("timeline")[i].get("state") == "change":
                        if not new_in or not new_out:
                            continue
                        match_json.get("timeline")[i]["in"] = new_in
                        match_json.get("timeline")[i]["out"] = new_out
                break
            except:
                continue


match_realtime_data = match_json

match_highlight_data = {
    "home_team": match_json.get("home_team"),
    "away_team": match_json.get("away_team"),
}

highlight_time_lines = []
for time_line in match_json.get("timeline"):
    if time_line.get("state") in ["goal", "owngoal", "change", "card1", "card2", "quarter_finish1"]:
        highlight_time_lines.append(time_line)
match_highlight_data["timeline"] = highlight_time_lines

# 실시간 경기 저장
file_name = f"{channel_number}_realtime.json"
file_path = os.path.join(os.getcwd(), file_name)
with open(file_path, "w", encoding="utf-8") as file:
    file.write(json.dumps(match_realtime_data, ensure_ascii=False, indent=2))
print(f"본경기 파일이 저장되었습니다: {file_path}")

# 하이라이트 경기 저장
file_name = f"{channel_number}_highlight.json"
file_path = os.path.join(os.getcwd(), file_name)
with open(file_path, "w") as file:
    file.write(json.dumps(match_highlight_data, ensure_ascii=False, indent=2))
print(f"하이라이트 파일이 저장되었습니다: {file_path}")

