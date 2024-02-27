import os
import logging
import pymysql
from pymysql.cursors import DictCursor
from dbutils.pooled_db import PooledDB
from fastapi import FastAPI, BackgroundTasks, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
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


class Database:
    def __init__(self, host, port, user, password, db):
        self.pool = PooledDB(
            creator=pymysql,
            maxconnections=5,
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
async def transcribe_audio(background_tasks: BackgroundTasks, voice_file_name: str):
    audio_file_path = os.path.join(voice_folder, voice_file_name)
    if not os.path.exists(audio_file_path):
        logger.error(f"File not found: {audio_file_path}")
        return {
            "result": "fail",
            "type": "search",
            "text": "음성 파일 찾기에 실패했습니다."
        }

    # 백그라운드로 음성 파일 STT 작업 시작
    background_tasks.add_task(get_ai_stt, audio_file_path, voice_file_name, 0)

    return {
        "TYPE": "request",
        "COMMAND": "controlAvatar",
        "CONTENTS": "",
        "DATA": {
            "status": "listen",
            "key": voice_file_name
        }
    }


def get_ai_stt(audio_file_path: str, voice_file_name: str, retry_count: int == 0):
    if retry_count > 5:
        return {
            "result": "fail",
            "type": "search",
            "text": "음성 변환에 실패하였습니다."
        }

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

        response = client.chat.completions.create(
            model=chat_model,
            messages=[
                {"role": "system", "content": "You are a language expert."},
                {"role": "user",
                 "content": "Extract the key words from the following context and tell me only those key words."
                            "Don't make up anything else, don't add anything."
                            "If there is a typo, please correct only the typo."
                            f"context: {transcript}"},
            ]
        )

        if response.choices:
            keyword = response.choices[0].message.content
            logger.info(f"Get keyword successful: {keyword}")

            cursor.execute("""
                insert into ai_stt(
                    voice_file_name, 
                    client_stt_question,
                    answer_type,
                    ai_chat_answer,
                    ai_chat_keyword,
                    insert_user,
                    update_user 
                ) values (
                    %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                voice_file_name,
                transcript,
                1,
                "",
                keyword,
                "client",
                "client",
            ))
            connection.commit()
        else:
            logger.error(f"Error speech to text, trying count: {retry_count}")
            retry_count += 1
            get_ai_stt(audio_file_path, voice_file_name, retry_count)
    except Exception as e:
        connection.rollback()
        cursor.close()
        connection.close()
        logger.error(f"Error speech to text: {e}, trying count: {retry_count}")
        retry_count += 1
        get_ai_stt(audio_file_path, voice_file_name, retry_count)
    finally:
        cursor.close()
        connection.close()


@app.get("/api/ai/result/{voice_file_name}")
def get_ai_keyword(voice_file_name: str):
    connection = db.get_connection()
    cursor = connection.cursor()
    try:
        cursor.execute("""
            select
                voice_file_name,
                client_stt_question,
                IF(answer_type = 1, 'search', 'text')                as answer_type,
                IF(answer_type = 1, ai_chat_keyword, ai_chat_answer) as ai_chat_answer,
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
            ai_chat_answer = result.get("ai_chat_answer")
            return {
                "result": "success",
                "type": answer_type,
                "text": ai_chat_answer
            }
        else:
            return {
                "result": "fail",
                "type": "search",
                "text": "아직 답변이 작성되지 않았습니다."
            }
    except Exception as e:
        logger.error(f"Error get keyword: {str(e)}")
        return {
            "result": "fail",
            "type": "search",
            "text": "DB조회 시 에러가 발생했습니다."
        }
