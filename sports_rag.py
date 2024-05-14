import json
import os
import time

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from dotenv import load_dotenv

load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

game_number = "2024042810041763599"
channel_number = "1"

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
