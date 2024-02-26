import streamlit as st
import requests
import os
from dotenv import load_dotenv


# .env 설정 불러오기
load_dotenv()

app_url = os.getenv("APP_URL")

# Streamlit 페이지 설정
st.title('파일 업로드 테스트')

# 파일 업로더 위젯
uploaded_file = st.file_uploader("파일을 선택해주세요", type=[".m4a", ".mp3", ".mp4", ".mpeg", ".mpga", ".wav", ".webm"])

# 업로드 버튼
if st.button('업로드'):
    if uploaded_file is not None:
        # 파일을 multipart/form-data로 서버에 업로드
        files = {'file': (uploaded_file.name, uploaded_file, uploaded_file.type)}
        response = requests.post(f"{app_url}/api/upload/", files=files)

        if response.status_code == 200:
            st.success('파일 업로드 성공!')
            st.json(response.json())
        else:
            st.error('파일 업로드 실패.')
            st.write(response.text)
    else:
        st.warning('파일을 선택해주세요.')
