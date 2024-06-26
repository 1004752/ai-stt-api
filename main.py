import os
import logging
import pymysql
import requests
import json
import json
import requests
from datetime import datetime, timedelta
from pydantic import BaseModel
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from fastapi import FastAPI, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from starlette.responses import JSONResponse
from openai import OpenAI
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


app.mount("/static", StaticFiles(directory=os.getenv("STATIC_FOLDER")), name="static")


################################################
# AI 캐릭터 API Endpoint
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
# VR Golf API Endpoint
################################################
@app.get("/api/vr/golf/{course_id}")
def get_golf_course_hole(course_id: int):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
             select course_id,
                    course_name,
                    total_hole_numbers,
                    total_distance,
                    course_level,
                    green_level,
                    address,
                    homepage,
                    tel_no
             from vr_golf_course
             where course_id = %s
        """, course_id)
        result = cursor.fetchone()

        if result:
            course_name = result.get("course_name")
            total_hole_numbers = result.get("total_hole_numbers")
            total_distance = result.get("total_distance")
            course_level = result.get("course_level")
            green_level = result.get("green_level")
            address = result.get("address")
            homepage = result.get("homepage")
            tel_no = result.get("tel_no")

            weather_data = get_korea_weather(58, 131)

            return {
                "result": "success",
                "course_id": course_id,
                "course_name": course_name,
                "total_hole_numbers": f"{total_hole_numbers}홀",
                "total_distance": f"{total_distance}m",
                "course_level": course_level,
                "green_level": green_level,
                "address": address,
                "homepage": homepage,
                "tel_no": tel_no,
                "weather": weather_data
            }
        else:
            return {
                "result": "fail",
                "type": "error",
                "text": "골프장 정보가 없습니다."
            }
    except Exception as e:
        logger.error(f"Error get tts: {str(e)}")
        return {
            "result": "fail",
            "type": "error",
            "text": "DB조회 시 에러가 발생했습니다."
        }


@app.get("/api/vr/golf/{course_id}/{hole_id}")
def get_golf_course_hole(course_id: int, hole_id: int):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
             select back_tee,
                    champ_tee,
                    front_tee,
                    senior_tee,
                    lady_tee,
                    map_image_link,
                    map_video_link,
                    voice_file_name
             from vr_golf_course_hole
             where course_id = %s
             and hole_id = %s
        """, (course_id, hole_id))
        result = cursor.fetchone()

        if result:
            back_tee = result.get("back_tee")
            champ_tee = result.get("champ_tee")
            front_tee = result.get("front_tee")
            senior_tee = result.get("senior_tee")
            lady_tee = result.get("lady_tee")
            map_image_link = result.get("map_image_link")
            map_video_link = result.get("map_video_link")
            voice_file_name = result.get("voice_file_name")

            return {
                "result": "success",
                "back_tee": f"{back_tee}m",
                "champ_tee": f"{champ_tee}m",
                "front_tee": f"{front_tee}m",
                "senior_tee": f"{senior_tee}m",
                "lady_tee": f"{lady_tee}m",
                "map_image_link": map_image_link,
                "map_video_link": map_video_link,
                "voice_link": f"{os.getenv('APP_URL')}/static/{voice_file_name}",
            }
        else:
            return {
                "result": "fail",
                "type": "error",
                "text": "홀 상세정보가 없습니다."
            }
    except Exception as e:
        logger.error(f"Error get tts: {str(e)}")
        return {
            "result": "fail",
            "type": "error",
            "text": "DB조회 시 에러가 발생했습니다."
        }


def deg_to_dir(deg):
    deg_code = {0: '북', 360: '북', 180: '남', 270: '서', 90: '동', 22.5:'북북동',
                45: '북동', 67.5: '동북동', 112.5: '동남동', 135: '남동', 157.5: '남남동',
                202.5: '남남서', 225: '남서', 247.5: '서남서', 292.5: '서북서', 315: '북서',
                337.5: '북북서'}

    close_dir = ''
    min_abs = 360
    if deg not in deg_code.keys():
        for key in deg_code.keys():
            if abs(key - deg) < min_abs :
                min_abs = abs(key - deg)
                close_dir = deg_code[key]
    else :
        close_dir = deg_code[deg]
    return close_dir


def get_korea_weather(nx: int, ny: int):
    serviceKey = os.getenv("WEATHER_SERVICE_API_KEY")

    result = {}

    now = datetime.now()
    if now.minute < 30:
        last_half_hour = (now.replace(minute=30, second=0, microsecond=0) - timedelta(hours=1))
    else:
        last_half_hour = now.replace(minute=30, second=0, microsecond=0)

    yyyymmdd = last_half_hour.strftime("%Y%m%d")
    hh24mi = last_half_hour.strftime("%H%M")

    base_date = yyyymmdd
    base_time = hh24mi

    result["base_date"] = base_date
    result["base_time"] = base_time

    input_d = datetime.strptime(base_date + base_time, "%Y%m%d%H%M")
    input_datetime = datetime.strftime(input_d, "%Y%m%d%H%M")
    input_date = input_datetime[:-4]
    input_time = input_datetime[-4:]

    url = f"http://apis.data.go.kr/1360000/VilageFcstInfoService_2.0/getUltraSrtFcst?serviceKey={serviceKey}" \
          f"&numOfRows=60&pageNo=1&dataType=json&base_date={base_date}&base_time={base_time}&nx={nx}&ny={ny}"
    response = requests.get(url, verify=False)
    res = json.loads(response.text)

    informations = dict()
    for items in res['response']['body']['items']['item']:
        cate = items['category']
        fcstTime = items['fcstTime']
        fcstValue = items['fcstValue']
        temp = dict()
        temp[cate] = fcstValue

        if fcstTime not in informations.keys() :
            informations[fcstTime] = dict()
        informations[fcstTime][cate] = fcstValue

    pyt_code = {0 : '강수 없음', 1 : '비', 2 : '비/눈', 3 : '눈', 5 : '빗방울', 6 : '진눈깨비', 7 : '눈날림'}
    sky_code = {1 : '맑음', 3 : '구름많음', 4 : '흐림'}

    for key, val in zip(informations.keys(), informations.values()):
        # 맑음(1), 구름많음(3), 흐림(4)
        if val['SKY']:
            sky_temp = sky_code[int(val['SKY'])]
            result["SKY"] = sky_temp

        # (초단기) 없음(0), 비(1), 비/눈(2), 눈(3), 빗방울(5), 빗방울눈날림(6), 눈날림(7)
        if val['PTY']:
            pty_temp = pyt_code[int(val['PTY'])]
            result["PTY"] = pty_temp

            # 강수 있는 경우
            if val['RN1'] != '강수없음':
                # RN1 1시간 강수량
                rn1_temp = val['RN1']
                result["RN1"] = f"시간당 {rn1_temp}mm"

        # 기온
        if val['T1H']:
            t1h_temp = float(val['T1H'])
            result["T1H"] = f"{t1h_temp}℃"

        # 습도
        if val['REH']:
            reh_temp = float(val['REH'])
            result["REH"] = f"{reh_temp}%"

        # 풍향/ 풍속
        if val['VEC'] and val['WSD']:
            vec_temp = deg_to_dir(float(val['VEC']))
            wsd_temp = val['WSD']
            result["VEC"] = vec_temp
            result["WSD"] = f"{wsd_temp}m/s"
        break
    return result


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


@app.get("/vision/main/getHomeUv")
async def get_home_uv(tape_code, bd_btime):
    new_session = requests.Session()
    _, session = login(new_session)

    url = f"http://vision.skstoa.com/vision/main/getHomeUv?bdBtime={bd_btime}&tapeCode={tape_code}"
    response = session.get(url)

    home_uv = {}
    if response.status_code == 200:
        home_uv = response.json()
        print(home_uv)
    return home_uv


@app.get("/vision/main/getPgmDetailInfo")
def get_pgm_detail_info(tape_code, bd_btime):
    new_session = requests.Session()
    _, session = login(new_session)

    url = f"http://vision.skstoa.com/vision/main/getPgmDetailInfo?bdBtime={bd_btime}&tapeCode={tape_code}"
    response = session.get(url)

    pgm_detail_list = {}
    if response.status_code == 200:
        pgm_detail_list = response.json()
        print(pgm_detail_list)
    return pgm_detail_list


@app.get("/vision/main/getWatchingAvg")
def get_watching_avg(tape_code, d_time, e_time):
    new_session = requests.Session()
    _, session = login(new_session)

    url = f"http://vision.skstoa.com/vision/main/getWatchingAvg?tapeCode={tape_code}&dTime={d_time}&eTime={e_time}"
    response = session.get(url)

    watching_avg = {}
    if response.status_code == 200:
        watching_avg = response.json()
    return watching_avg
