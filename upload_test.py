import streamlit as st
import requests
import os
from io import BytesIO
from dotenv import load_dotenv

# .env 설정 불러오기
load_dotenv()

app_url = os.getenv("APP_URL")
voice_folder = os.getenv("VOICE_FOLDER")

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


# 파일 다운로드를 위한 함수 정의
def download_file(file_path):
    with open(file_path, 'rb') as f:
        bytes_io = BytesIO(f.read())
    return bytes_io


# '/code/data' 폴더 내의 파일 리스트를 불러옴
files_with_mtime = [(file, os.path.getmtime(os.path.join(voice_folder, file))) for file in os.listdir(voice_folder)]
files_sorted = sorted(files_with_mtime, key=lambda x: x[1], reverse=True)
files = [file[0] for file in files_sorted]

# 파일 선택 위젯
selected_file = st.selectbox('Select a file to download:', files)

# 파일 다운로드 링크 제공
if st.button('Download'):
    file_path = os.path.join(voice_folder, selected_file)
    bytes_io = download_file(file_path)

    # Streamlit을 사용하여 파일 다운로드 링크 생성
    st.download_button(label="Download File",
                       data=bytes_io,
                       file_name=selected_file,
                       mime='application/octet-stream')
