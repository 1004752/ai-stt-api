import os
import logging
import pymysql
import requests
import json
import time
from fastapi import FastAPI, Request, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from starlette.responses import JSONResponse
from threading import Thread
from openai import OpenAI
from langchain_core.prompts.chat import ChatPromptTemplate, HumanMessagePromptTemplate, SystemMessagePromptTemplate
from langchain_openai import ChatOpenAI
from langchain_community.chat_models import ChatOllama
from langchain_core.messages import HumanMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from dotenv import load_dotenv

# .env 설정 불러오기
load_dotenv()

# FastAPI 실행
app = FastAPI()


# CORS 미들웨어 추가
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # 허용할 출처 목록, 모든 출처를 허용하려면 ["*"] 사용
    allow_credentials=True,
    allow_methods=["*"],  # 허용할 HTTP 메소드, 예: ["GET", "POST"]
    allow_headers=["*"],  # 클라이언트가 보낼 수 있는 헤더, 인증 헤더 등을 포함시키려면 명시적으로 추가
)

# OpenAI API 키 설정
OpenAI.api_key = os.getenv("OPENAI_API_KEY")
client = OpenAI()

# 음성 녹음 파일 위치
voice_folder = os.getenv("VOICE_FOLDER")

# AI 모델 설정
stt_model = os.getenv("STT_MODEL")
chat_model = os.getenv("CHAT_MODEL")

# 로거 설정
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# DB 설정
mysql_ip = os.getenv("MYSQL_IP")
mysql_port = os.getenv("MYSQL_PORT")
mysql_id = os.getenv("MYSQL_ID")
mysql_passwd = os.getenv("MYSQL_PASSWD")
mysql_db = os.getenv("MYSQL_DB")

# Eden AI API 키 설정
edenai_api_key = os.getenv("EDENAI_API_KEY")

# 서버 URL
app_url = os.getenv("APP_URL")


class Database:
    def __init__(self, host, port, user, password, db):
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=100,
            mincached=2,
            host=host,
            port=int(port),
            user=user,
            password=password,
            database=db,
            charset='utf8mb4',
            cursorclass=DictCursor
        )

    def get_connection(self):
        return self.pool.connection()


db = Database(mysql_ip, mysql_port, mysql_id, mysql_passwd, mysql_db)


################################################
# API Endpoint
################################################

@app.get("/")
async def root():
    return {"message": "Hello World"}


@app.post("/api/upload/")
async def upload_file(file: UploadFile = File(...)):
    try:
        file_path = os.path.join(voice_folder, file.filename)
        with open(file_path, "wb") as buffer:
            while True:
                chunk = file.file.read(1024)  # 1024 바이트씩 읽기
                if not chunk:
                    break
                buffer.write(chunk)

        return {"filename": file.filename, "message": "File uploaded successfully"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"message": f"Could not upload the file: {e}"})


# 파일 업로드 및 STT 처리를 위한 엔드포인트
@app.get("/api/ai/stt/{voice_file_name}")
async def speech_to_text(background_tasks: BackgroundTasks, voice_file_name: str):
    audio_file_path = os.path.join(voice_folder, voice_file_name)
    if not os.path.exists(audio_file_path):
        logger.error(f"File not found: {audio_file_path}")
        return {
            "result": "fail",
            "type": "error",
            "text": "음성 파일 찾기에 실패했습니다."
        }

    # 백그라운드로 음성 파일 STT 작업 시작
    background_tasks.add_task(get_ai_stt, audio_file_path, voice_file_name)

    return {
        "TYPE": "request",
        "COMMAND": "controlAvatar",
        "CONTENTS": "",
        "DATA": {
            "status": "listen",
            "key": voice_file_name
        }
    }


@app.get("/api/ai/result/{voice_file_name}")
def get_ai_keyword(voice_file_name: str):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            select
                voice_file_name,
                client_stt_question,
                case 
                    when answer_type = 1 then 'btv-search'
                    when answer_type = 2 then 'weather' 
                    else 'ai-answer' 
                end answer_type,
                ai_chat_answer,
                insert_user,
                insert_timestamp,
                update_user,
                update_timestamp
            from ai_stt
            where voice_file_name = %s
        """, voice_file_name)
        result = cursor.fetchone()

        if result:
            answer_type = result.get("answer_type")
            client_stt_question = result.get("client_stt_question")
            ai_chat_answer = result.get("ai_chat_answer")

            # BTV 검색인 경우 TTS 문구 수정
            if answer_type == "btv-search":
                ai_chat_answer = f"'{client_stt_question}'의 검색 결과입니다."

            cursor.execute("""
                select
                    id,
                    client_tts_text,
                    voice_file_url,
                    input_type,
                    response_status,
                    insert_user,
                    insert_timestamp,
                    update_user,
                    update_timestamp
                from ai_tts
                where response_status = 1
                and input_type = 3
                and client_tts_text = %s
                order by input_type, id desc
                limit 1 
            """, ai_chat_answer)
            tts_result = cursor.fetchone()

            if tts_result:
                id = tts_result.get("id")
                voice = tts_result.get("voice_file_url")

                set_tts_response_status(int(id))

                return {
                    "result": "success",
                    "type": answer_type,
                    "text": ai_chat_answer,
                    "voice": voice
                }
            else:
                return {
                    "result": "fail",
                    "type": "error",
                    "text": "아직 답변이 작성되지 않았습니다."
                }
        else:
            return {
                "result": "fail",
                "type": "error",
                "text": "아직 답변이 작성되지 않았습니다."
            }
    except Exception as e:
        logger.error(f"Error get keyword: {str(e)}")
        return {
            "result": "fail",
            "type": "error",
            "text": "DB조회 시 에러가 발생했습니다."
        }


class TTSRequest(BaseModel):
    input_type: str
    text: str


@app.post("/api/tts")
async def text_to_speech(background_tasks: BackgroundTasks, request: TTSRequest):
    input_type = request.input_type
    text = request.text

    # 백그라운드로 음성 파일 TTS 작업 시작
    background_tasks.add_task(get_ai_tts, input_type, text)

    return {
        "result": "success",
        "type": input_type,
        "text": text
    }


@app.get("/api/tts/result")
def get_tts_result():
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            select
                id,
                client_tts_text,
                voice_file_url,
                input_type,
                response_status,
                insert_user,
                insert_timestamp,
                update_user,
                update_timestamp
            from ai_tts
            where response_status = 1
            order by input_type, id desc
            limit 1
        """)
        result = cursor.fetchone()

        if result:
            tts_id = result .get("id")
            input_type = result.get("input_type")
            client_tts_text = result.get("client_tts_text")
            voice_file_url = result.get("voice_file_url")
            return {
                "result": "success",
                "tts_id": tts_id,
                "type": input_type,
                "text": client_tts_text,
                "voice": voice_file_url
            }
        else:
            return {
                "result": "fail",
                "type": "error",
                "text": "아직 음성이 생성되지 않았습니다."
            }
    except Exception as e:
        logger.error(f"Error get tts: {str(e)}")
        return {
            "result": "fail",
            "type": "error",
            "text": "DB조회 시 에러가 발생했습니다."
        }


@app.get("/api/tts/response/status/{tts_id}")
def set_tts_response_status(tts_id: int):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            update ai_tts set response_status = 2 
            where id = %s
        """, tts_id)
        connection.commit()

        return {
            "result": "success",
            "text": "수신완료 상태로 변경되었습니다.",
        }
    except Exception as e:
        connection.rollback()
        logger.error(f"Error Update DB: {e}")
        return {
            "result": "fail",
            "type": "error",
            "text": "DB저장 시 에러가 발생했습니다."
        }
    finally:
        cursor.close()
        connection.close()


@app.get("/api/ai/sports/{file_type}/{channel_id}")
def get_ai_sports(file_type: str, channel_id: int):
    text_file_path = os.path.join(voice_folder, f"{channel_id}_{file_type}.json")
    if not os.path.exists(text_file_path):
        logger.error(f"File not found: {text_file_path}")
        return {
            "result": "fail",
            "type": "error",
            "text": "경기 요약 파일 찾기에 실패했습니다."
        }

    with open(text_file_path, 'r') as f:
        match_json = json.load(f)
        return match_json

################################################
# 내부 처리 함수
################################################

def get_ai_tts(input_type: str, text: str):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        url = "https://api.edenai.run/v2/audio/text_to_speech"

        payload = {
            "response_as_dict": True,
            "attributes_as_list": False,
            "show_original_response": False,
            "rate": 0,
            "pitch": 0,
            "volume": 100,
            "sampling_rate": 0,
            "providers": "google",
            "text": text,
            "language": "ko",
            "option": "FEMALE"
        }
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "authorization": f"Bearer {edenai_api_key}"
        }

        response = requests.post(url, json=payload, headers=headers)

        data = json.loads(response.text)

        if data and data.get("google") and data.get("google").get("audio_resource_url"):
            voice_file_link = data.get("google").get("audio_resource_url")

            cursor.execute("""
                insert into ai_tts(
                    client_tts_text,
                    voice_file_url,
                    input_type,
                    response_status,
                    insert_user,
                    update_user 
                ) values (
                    %s, %s, %s, %s, %s, %s
                )
            """, (
                text,
                voice_file_link,
                input_type,
                1,
                "client",
                "client",
            ))
            connection.commit()
            logger.info("tts complete!")
        else:
            logger.error("Error text to speech: tts api error")
    except Exception as e:
        connection.rollback()
        logger.error(f"Error text to speech: {e}")
    finally:
        cursor.close()
        connection.close()


def get_ai_stt(audio_file_path: str, voice_file_name: str):
    retry_count = 0
    max_retries = 5

    while retry_count <= max_retries:
        connection = db.get_connection()
        cursor = connection.cursor()
        try:
            with open(audio_file_path, "rb") as audio_file:
                transcript = client.audio.transcriptions.create(
                    model=stt_model,
                    file=audio_file,
                    response_format="text"
                )
            logger.info(f"Transcription successful for file: {voice_file_name}")

            message, answer_type = send_query(transcript)

            if answer_type > 0:
                cursor.execute("""
                    insert into ai_stt(
                        voice_file_name, 
                        client_stt_question,
                        answer_type,
                        ai_chat_answer,
                        insert_user,
                        update_user 
                    ) values (
                        %s, %s, %s, %s, %s, %s
                    )
                """, (
                    voice_file_name,
                    transcript,
                    answer_type,
                    message,
                    "client",
                    "client",
                ))

                # BTV 검색인 경우 TTS 문구 수정
                if answer_type == 1:
                    message = f"'{transcript}'의 검색 결과입니다."

                # TTS 생성 API 호출
                tts_url = f"{app_url}/api/tts"
                payload = {
                    "input_type": "3",
                    "text": message
                }
                headers = {
                    "accept": "application/json",
                    "content-type": "application/json",
                }
                response = requests.post(tts_url, json=payload, headers=headers)
                tts_result = json.loads(response.text)
                if tts_result.get("result") == "success":
                    logger.info("text to speech API Call Complete.")
                    connection.commit()
                    retry_count += 10
                else:
                    logger.error(f"Error text to speech, trying count: {retry_count}")
                    retry_count += 1
            else:
                logger.error(f"Error speech to text, trying count: {retry_count}")
                retry_count += 1
        except Exception as e:
            connection.rollback()
            logger.error(f"Error speech to text: {e}, trying count: {retry_count}")
            retry_count += 1
            if retry_count > max_retries:
                logger.error("Maximum retry attempts reached. Giving up.")
                break
        finally:
            cursor.close()
            connection.close()

        if retry_count <= max_retries:
            break


def current_weather_info(city: str):
    '''
    도시 파라미터를 입려받아 현재 날씨정보를 반환합니다
    :param city: 도시
    '''
    api_key = "cae9c532caea0c33c93547a70879e455"

    url = f'https://api.openweathermap.org/data/2.5/weather?q={city}&appid={api_key}'
    response = requests.get(url)
    data = response.json()

    # print(city, data)

    weather = data['weather'][0]['description']
    temp = data['main']['temp'] - 273.15  # K to C
    humidity = data['main']['humidity']
    return recommand_clothes(weather, temp, humidity)


def recommand_clothes(weather, temp, humidity):
    prompt = f'''다음 정보로 날씨에 대한 설명을 한글 100자 이내로 답변해줘.
    \n날씨: {weather}
    \n온도: {temp}
    \n습도: {humidity}
    '''

    messages = [
        {"role": "system", "content": "너는 전문 기상 캐스터야."},
        {"role": "user", "content": prompt}
    ]
    response = client.chat.completions.create(
        model="gpt-3.5-turbo",
        messages=messages,
        temperature=0.9,
        max_tokens=1000,
    )

    answer = response.choices[0].message.content.strip()
    return answer


def search_media_keywords(sentence: str):
    '''
    방송 매체에 관련한 질문에 대답하기
    :param sentence: 방송 매체에 관련한 질문
    '''
    response = client.chat.completions.create(
        model=chat_model,
        messages=[
            {"role": "system", "content": "You are a language expert."},
            {"role": "user",
             "content": "Extract the key words from the following context and tell me only those key words."
                        "Please separate the extracted keywords with commas"
                        "Don't make up anything else, don't add anything."
                        "If there is a typo, please correct only the typo."
                        f"context: {sentence}"},
        ]
    )

    keyword = None
    if response.choices:
        keyword = response.choices[0].message.content
        logger.info(f"Extract keyword successful: {keyword}")

    return keyword


def send_query(prompt):
    try:
        # Step 1: finstate_summary 함수 준비
        messages = [{"role": "user", "content": f"{prompt}"}]

        functions = [
            {'name': 'search_media_keywords',
             'description': '방송 매체에 관련한 질문에 대답하기\n:param sentence: 방송 매체에 관련한 질문',
             'parameters': {'type': 'object',
                            'properties': {'sentence': {'type': 'string'}},
                            'required': ['sentence']}},
            {'name': 'current_weather_info',
             'description': '도시 파라미터를 입려받아 현재 날씨정보를 반환합니다\n:param city: 도시',
             'parameters': {'type': 'object',
                            'properties': {'city': {'type': 'string'}},
                            'required': ['city']}},
        ]

        # Step 2: 프롬프트와 함께 functions 목록과 호출여부를 GPT에 전달
        response = client.chat.completions.create(
            model="gpt-3.5-turbo-0613",
            messages=messages,
            functions=functions,  # 함수
            function_call="auto",  # auto=기본값(functions 지정시)
        )

        response_message = response.choices[0].message

        answer_type = 4  # 4(default) type: 기타

        if not response_message.function_call:  # 함수호출이 아니라면
            messages.append(response_message.content)
            return response_message.content, answer_type

        # Step 3: GPT가 어떤 함수를 호출을 원하는지 알아내어 지정한 함수를 호출
        available_functions = {
            "search_media_keywords": search_media_keywords,
            "current_weather_info": current_weather_info
        }
        function_name = response_message.function_call.name
        arguments = response_message.function_call.arguments
        func = available_functions[function_name]
        args = json.loads(arguments)
        func_response = func(**args)

        if function_name == "search_media_keywords":  # 1 type: BTV 검색
            answer_type = 1
        elif function_name == "current_weather_info":  # 2 type: 날씨
            answer_type = 2

        return func_response, answer_type
    except Exception as e:
        return e, -1


################################################
# vision 크롤링
################################################
data = {}

def login(session):
    login_url = "http://skstoa-vision-931293320.ap-northeast-2.elb.amazonaws.com:19090/auth/login?user_id=jungsik.yeo%40sk.com&user_pw=test%21q2w&force=true"

    # 로그인 요청 보내기
    response = session.get(login_url)

    # 로그인 성공 여부 확인
    if response.status_code == 200:
        json_data = response.json()
        if json_data.get("authResult") == "SUCCESS":
            token = json_data.get("data", {}).get("token")
            if token:
                session.headers.update({"X-Auth-Token": f"{token}"})
                return True, session
            else:
                print("토큰이 없습니다.")
                return False, session
        else:
            print("로그인 실패:", json_data.get("message"))
            return False, session
    else:
        print("로그인 요청 실패:", response.status_code)
        return False, session


def get_channel_list(session):
    url = "http://skstoa-vision-931293320.ap-northeast-2.elb.amazonaws.com:19090/common/channelList"
    response = session.get(url)

    channel_list = []
    if response.status_code == 200:
        json_data = response.json()
        if json_data.get("message") == "SUCCESS":
            channel_list = json_data.get("data")
    return channel_list


def get_pgm_list(session, channel_code):
    url = f"http://skstoa-vision-931293320.ap-northeast-2.elb.amazonaws.com:19090/main/pgmList?channelCode={channel_code}"
    response = session.get(url)

    pgm_list = []
    if response.status_code == 200:
        json_data = response.json()
        if json_data.get("message") == "SUCCESS":
            pgm_list = json_data.get("data")
    return pgm_list


def get_home_uv(session, tape_code, bd_btime):
    url = f"http://vision.skstoa.com/vision/main/getHomeUv?bdBtime={bd_btime}&tapeCode={tape_code}"
    response = session.get(url)

    home_uv = {}
    if response.status_code == 200:
        home_uv = response.json()
    return home_uv


def get_pgm_detail_info(session, tape_code, bd_btime):
    url = f"http://vision.skstoa.com/vision/main/getPgmDetailInfo?bdBtime={bd_btime}&tapeCode={tape_code}"
    response = session.get(url)

    pgm_detail_info = {}
    if response.status_code == 200:
        pgm_detail_list = response.json()
        for pgm_detail in pgm_detail_list:
            pgm_detail_info = pgm_detail
    return pgm_detail_info


def get_watching_avg(session, tape_code, d_time, e_time):
    url = f"http://vision.skstoa.com/vision/main/getWatchingAvg?tapeCode={tape_code}&dTime={d_time}&eTime={e_time}"
    response = session.get(url)

    watching_avg = {}
    if response.status_code == 200:
        watching_avg = response.json()
    return watching_avg


def get_make_tts(session, text):
    url = f"{app_url}/api/tts"
    data = {
        "input_type": "2",
        "text": text
    }
    print(data)
    headers = {"Content-Type": "application/json"}
    response = session.post(url, json=data, headers=headers)

    result = {}
    if response.status_code == 200:
        result = response.json()
    return result


def crawl_and_analyze():
    global data
    on_air_pgm = None
    prev_pgm = None

    # 세션 객체 생성
    new_session = requests.Session()
    sleep_time_1min = 20
    sleep_time_5min = sleep_time_1min * 1

    while True:
        login_flag, session = login(new_session)
        sleep_time = sleep_time_1min

        # 로그인 시도
        if login_flag:
            print("로그인 성공")
        else:
            print("로그인 실패")
            time.sleep(sleep_time)
            continue

        # 채널 목록 추출
        channel_list = get_channel_list(session)
        if channel_list:
            # 첫번째 채널의 방송 상품 목록 추출
            channel_code = channel_list[0].get("channelCode")
            pgm_list = get_pgm_list(session, channel_code)
        else:
            print("채널 추출 실패")
            time.sleep(sleep_time)
            continue

        # 현재 방송 상품 추출
        now = time.strftime('%Y%m%d%H%M')
        for pgm in pgm_list:
            if pgm.get("startDate") <= now <= pgm.get("endDate"):
                on_air_pgm = pgm
                break

        # 현재 방송 상품 없는 경우
        if not on_air_pgm:
            print("상품을 찾을 수 없습니다.")
            time.sleep(sleep_time)
            continue

        # 상품이 변경되었을 경우 데이터 초기화
        if prev_pgm:
            if prev_pgm.get("pgmName") != on_air_pgm.get("pgmName"):
                data.clear()
                prev_pgm = on_air_pgm
        else:
            prev_pgm = on_air_pgm

        # print(on_air_pgm)

        # 현재 방송의 실시간 데이터 추출
        # home_uv = get_home_uv(session, on_air_pgm.get("tapeCode"), f"{on_air_pgm.get('startDate')}00")
        # pgm_detail_info = get_pgm_detail_info(session, on_air_pgm.get("tapeCode"), f"{on_air_pgm.get('startDate')}00")
        # print(home_uv)
        # print(pgm_detail_info)
        watching_avg = get_watching_avg(session,
                                        on_air_pgm.get("tapeCode"),
                                        f"{on_air_pgm.get('startDate')}00",
                                        f"{on_air_pgm.get('endDate')}00",)

        current_data = {
            "viewers": watching_avg.get("sessionCount"),
            # "주문액": watching_avg.get("orderAmt"),
            "calls": watching_avg.get("callInAmt"),
        }

        # print(watching_avg)
        # print(current_data)

        # LLM 분석 및 코멘트 생성
        if current_data.get("viewers") and len(current_data.get("viewers")) >= 1:
            # data = get_mistral_7b(on_air_pgm, current_data)
            # data = get_llama2_13b(on_air_pgm, current_data)
            data = get_gpt4(on_air_pgm, current_data)
            data["sessionCount"] = watching_avg.get("sessionCount")
            # data["orderAmt"] = watching_avg.get("orderAmt")
            data["callInAmt"] = watching_avg.get("callInAmt")
            # print(data)
            # if data.get("change") == "Y":
            if data.get("change"):
                get_make_tts(session, data.get("comment"))
                sleep_time = sleep_time_5min

        time.sleep(sleep_time)  # 60초마다 반복


def get_mistral_7b(on_air_pgm, current_data):
    llm = ChatOllama(temperature=0.1, model="mistral")

    template = (
        """
            <s>[INST] You are an analyst and marketer specializing in broadcast products.
            We analyze real-time data of broadcast products and answer them in the following form.
            Please don't add anything other than the form.
            form:[/INST]
            {context}
            </s>
        """
    )
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_template = (
        "Here is the latest data trend for the product '{pgm_name}':"
        "{current_data}"
        "Please analyze the trend within the last 5 minutes and make comments that induce consumers to purchase the situation only if the trend is increasing."
        "Comment, please make a brief marketing phrase in 50 characters or less, including increasing data."
        "If the trend is on the decline within the last 5 minutes, please answer with situation change 'N'."
        # "Please answer in the form of json."
    )
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)

    chat_prompt = ChatPromptTemplate.from_messages(
        [system_message_prompt, human_message_prompt]
    )

    pgm_name = on_air_pgm.get("pgmName")
    context = """
        {
            "change": "'Y' or 'N'",
            "comment": "comment on change situation"
        }
    """

    dumps = json.dumps(current_data, indent=2)

    chain = chat_prompt | llm | StrOutputParser()

    result = chain.invoke({"current_data": dumps, "pgm_name": pgm_name, "context": context})
    print(result)

    try:
        json_result = json.loads(result.replace("<|im_end|>", ""))
        return json_result
    except json.JSONDecodeError:
        print("JSON 형식이 올바르지 않습니다.")
        return {
            "change": "N",
            "comment": "JSON 형식이 올바르지 않습니다."
        }


def get_llama2_13b(on_air_pgm, current_data):
    llm = ChatOllama(temperature=0.1, model="mistral")

    template = (
        """
            당신은 방송 상품 전문 분석가이자 마케터입니다.
            방송 상품의 실시간 데이터를 분석하는 역할을 담당합니다.
        """
    )
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_template = (
        "다음은 상품 '{pgm_name}'의 최근 데이터 추이입니다:\n"
        "{current_data}\n\n"
        "최근 5분 이내의 추이를 분석하고 상승중인 항목에 대해 설명해주세요.\n"
    )
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)

    chat_prompt = ChatPromptTemplate.from_messages(
        [system_message_prompt, human_message_prompt]
    )

    pgm_name = on_air_pgm.get("pgmName")
    context = """
        {
            "change": "데이터 변화가 크면 Y, 작으면 N",
            "comment": "변화 상황에 대한 코멘트"
        }
    """

    dumps = json.dumps(current_data, indent=2)

    chain = chat_prompt | llm | StrOutputParser()

    result = chain.invoke({"current_data": dumps, "pgm_name": pgm_name, "context": context})
    print(result)

    try:
        json_result = json.loads(result.replace("<|im_end|>", ""))
        return json_result
    except json.JSONDecodeError:
        print("JSON 형식이 올바르지 않습니다.")
        return {
            "change": "N",
            "comment": "SON 형식이 올바르지 않습니다."
        }


def get_gpt4(on_air_pgm, current_data):
    os.environ["OPENAI_API_KEY"] = os.getenv("OPENAI_API_KEY")

    llm = ChatOpenAI(
        model_name="gpt-4-turbo-preview",
        temperature=0.1,
    )

    template = (
        """
            당신은 방송 상품 전문 분석가이자 마케터입니다.
            방송 상품의 실시간 데이터를 분석해서 다음 양식으로 답변합니다.
            양식 외에는 어떤것도 덧붙이지 마세요.
            ------
            {context}
        """
    )
    system_message_prompt = SystemMessagePromptTemplate.from_template(template)
    human_template = (
        "다음은 상품 '{pgm_name}'의 최근 데이터 추이입니다:\n"
        "{current_data}\n\n"
        # "최근 5분 이내의 추이를 분석하고 증가 추세인 경우에만 소비자에게 상황에 대한 구매를 유도하는 코멘트를 만들어주세요.\n"
        # "코멘트는 증가하는 데이터를 포함해서 간략한 마케팅 문구를 50자 이내로 만들어주세요.\n"
        # "최근 5분 이내 추이가 하락 추세면 상황변화 N으로 답해주세요.\n"
        "최근 5분 이내의 추이를 분석하고 소비자에게 상황에 대한 구매를 유도하는 코멘트를 만들어주세요.\n"
        "코멘트는 간략한 마케팅 문구를 50자 이내로 만들어주세요.\n"
        "json형태 양식으로 답변해주세요."
    )
    human_message_prompt = HumanMessagePromptTemplate.from_template(human_template)

    chat_prompt = ChatPromptTemplate.from_messages(
        [system_message_prompt, human_message_prompt]
    )

    context = """
        {
            "change": "데이터 변화가 크면 Y, 작으면 N",
            "comment": "변화 상황에 대한 코멘트"
        }
    """
    pgm_name = on_air_pgm.get("pgmName")
    result = llm.invoke(
        chat_prompt.format_prompt(
            context=context,
            pgm_name=pgm_name,
            current_data=current_data
        ).to_messages()
    )

    print(result.content)

    try:
        json_result = json.loads(result.content)
        return json_result
    except json.JSONDecodeError:
        print("JSON 형식이 올바르지 않습니다.")
        return {
            "change": "N",
            "comment": "JSON 형식이 올바르지 않습니다."
        }


@app.get("/api/analysis/{product_name}")
async def get_analysis(product_name: str):
    try:
        with open(f"{product_name}_analysis.txt", "r") as f:
            analysis = f.read()
        return {"analysis": analysis}
    except FileNotFoundError:
        return {"analysis": ""}


def run_scheduler():
    crawl_and_analyze()


@app.on_event("startup")
async def startup_event():
    Thread(target=run_scheduler).start()
