import json
import os
from dotenv import load_dotenv

# .env 설정 불러오기
load_dotenv()

os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")


system_content = """너는 유능한 축구중계 데이터 분석가야. 너는 축구 중계 요약 코멘트를 json형태의 데이터로 변환해야해."""
prompt_Q = []
assistant_content_A = []
channel_number = "test"

with open(f"{channel_number}_realtime.json", "r") as f:
    match_json = json.load(f)
    timelines = match_json["timeline"]

    for timeline in timelines:
        second_text = "'"
        prompt_Q.append(f"[{timeline.get('time').replace(second_text,'`')}]{timeline.get('desc')}")
        # print(timeline)

        train_text = ""
        for key, value in enumerate(timeline):
            if key > 0:
                train_text += ","
            if value == "time":
                train_text += f"'{value}':'{timeline.get(value).replace(second_text,'`')}'"
            else:
                train_text += f"'{value}':'{timeline.get(value)}'"
        assistant_content_A.append(f"{{{{{train_text}}}}}")

    for i, desired_A in enumerate(assistant_content_A):
        line_out = {"messages": [{"role": "system", "content": system_content},
                                 {"role": "user", "content": prompt_Q[i]},
                                 {"role": "assistant", "content": desired_A}]}

        print(json.dumps(line_out, ensure_ascii=False))

        # 훈련 데이터 생성
        file_name = "train_data.jsonl"
        file_path = os.path.join(os.getcwd(), file_name)
        with open(file_path, "a") as file:
            file.write(json.dumps(line_out, ensure_ascii=False))
            file.write("\n")
    print(f"훈련 데이터 파일이 저장되었습니다: {file_path}")
